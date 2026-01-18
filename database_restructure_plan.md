# Database Restructure Plan for Project Explorer

## Executive Summary

This plan creates an optimal database schema for the project/unit/building explorer from scratch, leveraging all available data from CSV files to provide comprehensive project information with proper English naming.

## Current Issues Identified

### 1. **Missing English Project Names**
- Current `projects` table only uses Arabic names from Projects.csv
- Units.csv and Buildings.csv contain both `project_name_ar` and `project_name_en` fields
- **Impact**: Supply page displays Arabic names instead of English

### 2. **Underutilized Data**
- Rich project name data in Units.csv and Buildings.csv not being imported
- **Coverage Analysis**: ~2,708 projects have English names available
- Current schema doesn't leverage all available CSV columns

### 3. **Suboptimal Design**
- Missing project name fields that exist in source data
- No unified view for project catalog functionality

## Optimal Schema Design (Fresh Database)

### 1. **Enhanced Projects Table**

```sql
-- Update Projects table to include English names
-- Projects.csv only has Arabic, but we'll populate English from Units/Buildings
CREATE TABLE projects (
    project_id INTEGER PRIMARY KEY,
    project_number INTEGER UNIQUE,
    project_name_ar VARCHAR(255),  -- From Projects.csv (renamed from project_name)
    project_name_en VARCHAR(255),  -- Populated from Units.csv data
    -- ... all other existing fields remain the same
);
```

### 2. **Enhanced Buildings Table**

```sql  
-- Buildings table utilizing all available CSV data
CREATE TABLE buildings (
    -- ... existing fields ...
    project_name_ar VARCHAR(255),  -- Available in Buildings.csv, currently not imported
    project_name_en VARCHAR(255),  -- Available in Buildings.csv, currently not imported
    -- ... rest of fields
);
```

### 3. **Enhanced Units Table**

```sql
-- Units table utilizing all available CSV data  
CREATE TABLE units (
    -- ... existing fields ...
    project_name_ar VARCHAR(255),  -- Available in Units.csv, currently not imported
    project_name_en VARCHAR(255),  -- Available in Units.csv, currently not imported
    -- ... rest of fields
);
```

### 4. **Project Explorer View**

```sql
-- Project explorer view with smart name selection
CREATE OR REPLACE VIEW project_explorer AS
SELECT 
    p.project_id,
    -- Smart name selection: English if available, else Arabic
    COALESCE(p.project_name_en, p.project_name_ar) as display_name,
    p.project_name_ar,
    p.project_name_en,
    p.project_start_date,
    p.project_end_date,
    p.percent_completed,
    p.project_status,
    d.developer_name_en as developer_name,
    a.name_en as area_name,
    mp.master_project_en as master_project_name,
    p.no_of_buildings,
    p.no_of_units,
    COUNT(DISTINCT b.property_id) as actual_buildings_count,
    COUNT(DISTINCT u.property_id) as actual_units_count
FROM projects p
LEFT JOIN developers d ON p.developer_id = d.developer_id
LEFT JOIN areas a ON p.area_id = a.area_id
LEFT JOIN buildings b ON p.project_id = b.project_id
LEFT JOIN units u ON p.project_id = u.project_id
LEFT JOIN (
    SELECT DISTINCT u.project_id, mp.master_project_en
    FROM units u 
    JOIN master_projects mp ON u.master_project_id = mp.master_project_id
) mp ON p.project_id = mp.project_id
GROUP BY p.project_id, p.project_name_ar, p.project_name_en, p.project_start_date, 
         p.project_end_date, p.percent_completed, p.project_status, 
         d.developer_name_en, a.name_en, mp.master_project_en, 
         p.no_of_buildings, p.no_of_units;
```

## Required Changes

### 1. **Update SQLModel Classes**

```python
# In app/db/models/properties.py

class Project(SQLModel, table=True):
    __tablename__ = "projects"
    
    project_id: int = Field(primary_key=True)
    project_number: Optional[int] = Field(default=None, unique=True)
    project_name_ar: Optional[str] = Field(default=None, max_length=255)  # Renamed from project_name
    project_name_en: Optional[str] = Field(default=None, max_length=255)  # Populated during ETL from Units.csv
    # ... all other existing fields remain unchanged

class Building(SQLModel, table=True):
    __tablename__ = "buildings"
    
    # ... existing fields ...
    project_name_ar: Optional[str] = Field(default=None, max_length=255)  # From Buildings.csv
    project_name_en: Optional[str] = Field(default=None, max_length=255)  # From Buildings.csv
    # ... rest of existing fields

class Unit(SQLModel, table=True):
    __tablename__ = "units"
    
    # ... existing fields ...
    project_name_ar: Optional[str] = Field(default=None, max_length=255)  # From Units.csv
    project_name_en: Optional[str] = Field(default=None, max_length=255)  # From Units.csv
    # ... rest of existing fields
```

## Critical Review of Current Approach

### **Potential Issues Identified**

#### 1. **Performance Impact**
- **Problem**: Reading Units.csv during every chunk of Projects.csv processing could significantly slow down ETL
- **Impact**: Units.csv has ~600K rows - reading it repeatedly during chunked processing is inefficient
- **ETL Architecture Conflict**: Your ETL is designed for chunked processing, but this approach reads entire Units.csv for each chunk

#### 2. **Memory Concerns**
- **Problem**: Loading Units.csv into memory during Projects processing increases memory footprint
- **Impact**: Could cause memory issues during large ETL runs

#### 3. **Error Handling & Dependencies**  
- **Problem**: Projects processing now depends on Units.csv existing and being valid
- **Impact**: If Units.csv is corrupted, Projects processing fails entirely
- **Robustness**: Creates fragile dependency chain

#### 4. **Incremental ETL Issues**
- **Problem**: During incremental updates, we'd re-read Units.csv even for small Projects changes
- **Impact**: Inefficient for daily incremental runs

#### 5. **Data Consistency**
- **Problem**: Only reads from Units.csv, ignores Buildings.csv project names
- **Impact**: Could miss English names that exist in Buildings.csv but not Units.csv

### **Improved Approach: ETL Pre-Processing Cache**

Instead of reading Units.csv during Projects processing, let's create an in-memory cache at ETL startup:

```python
# Enhanced approach in backend/scripts/etl/runner.py

class ProjectNameCache:
    """Cache for project English names loaded at ETL startup"""
    
    def __init__(self, current_dir: Path):
        self.cache = {}
        self._load_project_names(current_dir)
    
    def _load_project_names(self, data_dir: Path):
        """Load project names from both Units.csv and Buildings.csv"""
        project_names = {}
        
        # Read from Units.csv
        units_file = data_dir / "Units.csv"
        if units_file.exists():
            try:
                units_df = pl.read_csv(
                    units_file,
                    columns=["project_id", "project_name_en"]
                ).filter(
                    pl.col("project_name_en").is_not_null() & 
                    (pl.col("project_name_en") != "")
                ).unique(subset=["project_id"])
                
                for row in units_df.iter_rows(named=True):
                    project_names[row["project_id"]] = row["project_name_en"]
                    
            except Exception as e:
                print(f"Warning: Could not load project names from Units.csv: {e}")
        
        # Read from Buildings.csv (fallback for projects not in Units)
        buildings_file = data_dir / "Buildings.csv" 
        if buildings_file.exists():
            try:
                buildings_df = pl.read_csv(
                    buildings_file,
                    columns=["project_id", "project_name_en"]
                ).filter(
                    pl.col("project_name_en").is_not_null() & 
                    (pl.col("project_name_en") != "")
                ).unique(subset=["project_id"])
                
                for row in buildings_df.iter_rows(named=True):
                    # Only add if not already in cache (Units.csv takes precedence)
                    if row["project_id"] not in project_names:
                        project_names[row["project_id"]] = row["project_name_en"]
                        
            except Exception as e:
                print(f"Warning: Could not load project names from Buildings.csv: {e}")
        
        self.cache = project_names
        print(f"Loaded {len(self.cache)} project English names into cache")
    
    def get_english_name(self, project_id: int) -> Optional[str]:
        """Get English name for project_id"""
        return self.cache.get(project_id)

# Modified enhancement function
def enhance_projects_with_english_names(df: pl.DataFrame, name_cache: ProjectNameCache) -> pl.DataFrame:
    """Enhance projects DataFrame using pre-loaded cache"""
    if df.is_empty():
        return df
    
    # Add project_name_en column using cache
    english_names = [
        name_cache.get_english_name(row["project_id"]) 
        for row in df.select("project_id").iter_rows(named=True)
    ]
    
    return df.with_columns(
        pl.Series("project_name_en", english_names)
    )
```

### **Updated ETL Runner Integration**

```python
# Updated backend/scripts/etl/runner.py

def run_etl(
    tables: list[str] | None = None,
    full_refresh: bool = False,
    data_dir: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Run the ETL pipeline with project name caching."""
    logger = setup_logging()
    
    current_dir, previous_dir, current_pks_dir, previous_pks_dir = get_data_paths(data_dir)
    
    # Initialize project name cache at startup (only once)
    project_name_cache = ProjectNameCache(current_dir)
    
    # ... existing ETL logic ...
    
    try:
        for table_name in tables_to_process:
            config = all_configs.get(table_name)
            if not config:
                continue
                
            # Pass cache to projects processing
            if table_name == "projects":
                results.append(
                    process_csv_table(
                        conn, config, current_dir, previous_dir, 
                        current_pks_dir, previous_pks_dir, logger, 
                        full_refresh, dry_run, project_name_cache
                    )
                )
            else:
                results.append(
                    process_csv_table(
                        conn, config, current_dir, previous_dir,
                        current_pks_dir, previous_pks_dir, logger,
                        full_refresh, dry_run
                    )
                )
```

### **Benefits of Improved Approach**

#### ✅ **Performance Optimized**
- **Single file read**: Units.csv and Buildings.csv read only once at ETL startup
- **In-memory cache**: Fast lookups during chunked processing
- **No repeated I/O**: Eliminates file reads during Projects processing chunks

#### ✅ **Memory Efficient** 
- **Minimal footprint**: Cache only stores project_id → name mappings (not full CSV data)
- **Predictable**: Memory usage known upfront, no surprises during processing

#### ✅ **Robust Error Handling**
- **Graceful degradation**: If name loading fails, Projects processing continues with Arabic names
- **Independent failures**: Units.csv and Buildings.csv failures are isolated
- **No blocking**: Projects processing never fails due to name enhancement issues

#### ✅ **Data Quality**
- **Multiple sources**: Uses both Units.csv and Buildings.csv for comprehensive coverage
- **Precedence rules**: Clear priority (Units.csv > Buildings.csv)
- **Conflict resolution**: Built-in handling of duplicate project IDs

#### ✅ **ETL Architecture Alignment**
- **Chunked processing friendly**: Cache lookups work perfectly with chunks
- **Incremental compatible**: Cache refreshed only when needed
- **Performance characteristics**: Maintains your ETL's speed advantages

### **Alternative: Even Simpler Approach**

If you want to keep it very simple, we could also just:

1. **Add `project_name_en` column** to Projects model (empty initially)
2. **Let ETL populate Buildings/Units** with their project names as normal
3. **Post-ETL one-liner**: `UPDATE projects SET project_name_en = (SELECT DISTINCT project_name_en FROM units WHERE units.project_id = projects.project_id LIMIT 1)`

**Pros**: Extremely simple, no ETL changes
**Cons**: Requires post-ETL step (which you wanted to avoid)

### **Recommendation**

I recommend the **ProjectNameCache approach** because it:
- ✅ Solves all the performance and architecture issues
- ✅ Integrates cleanly with your existing ETL patterns  
- ✅ Provides comprehensive data coverage
- ✅ Maintains robustness and error handling
- ✅ Keeps everything within the ETL process (no post-processing)

```sql
-- Project explorer view using direct columns (no lookup table needed)
CREATE OR REPLACE VIEW project_explorer AS
SELECT 
    p.project_id,
    -- Smart name selection: English if available, else Arabic
    COALESCE(p.project_name_en, p.project_name_ar) as display_name,
    p.project_name_ar,
    p.project_name_en,
    p.project_start_date,
    p.project_end_date,
    p.percent_completed,
    p.project_status,
    d.developer_name_en as developer_name,
    a.name_en as area_name,
    mp.master_project_en as master_project_name,
    p.no_of_buildings,
    p.no_of_units,
    COUNT(DISTINCT b.property_id) as actual_buildings_count,
    COUNT(DISTINCT u.property_id) as actual_units_count
FROM projects p
LEFT JOIN developers d ON p.developer_id = d.developer_id
LEFT JOIN areas a ON p.area_id = a.area_id
LEFT JOIN buildings b ON p.project_id = b.project_id
LEFT JOIN units u ON p.project_id = u.project_id
LEFT JOIN (
    SELECT DISTINCT u.project_id, mp.master_project_en
    FROM units u 
    JOIN master_projects mp ON u.master_project_id = mp.master_project_id
) mp ON p.project_id = mp.project_id
GROUP BY p.project_id, p.project_name_ar, p.project_name_en, p.project_start_date, 
         p.project_end_date, p.percent_completed, p.project_status, 
         d.developer_name_en, a.name_en, mp.master_project_en, 
         p.no_of_buildings, p.no_of_units;
```

### 6. **Update Supply Service**
```

```python
# Update app/services/supply_service.py - back to simple approach
async def get_upcoming_projects_with_english_names(db: AsyncSession) -> List[Project]:
    """Get all active/upcoming projects with English name support."""
    stmt = (
        select(Project)
        .options(selectinload(Project.developer), selectinload(Project.area))
        .where(
            Project.project_start_date.isnot(None),
            Project.completion_date.is_(None),
            Project.cancellation_date.is_(None),
        )
        .order_by(
            Project.project_end_date.asc().nulls_last(), 
            coalesce(Project.project_name_en, Project.project_name_ar).asc()
        )
    )
    result = await db.exec(stmt)
    return list(result.all())
```

```python
# Update app/routers/supply.py - back to simple approach
@router.get("/upcoming-projects", response_model=UpcomingProjectsResponse)
@cached_endpoint(prefix="upcoming_projects", expire=3600)
async def list_upcoming_projects(db: AsyncSession = Depends(get_db_session)):
    """Get all upcoming/active projects with English names when available."""
    projects = await get_upcoming_projects_with_english_names(db)

    result = []
    for project in projects:
        # Use English name if available, fallback to Arabic
        project_name = project.project_name_en or project.project_name_ar
        
        project_data = {
            "project_id": project.project_id,
            "project_name": project_name,  # Now shows English when available
            "developer_name": project.developer.developer_name_en if project.developer else "Unknown",
            "developer_id": project.developer_id,
            "area_name": project.area.name_en if project.area else "Unknown",
            "project_start_date": project.project_start_date,
            "project_end_date": project.project_end_date,
            "percent_completed": project.percent_completed or 0,
            "no_of_buildings": project.no_of_buildings,
            "no_of_units": project.no_of_units,
        }
        result.append(UpcomingProjectResponse.model_validate(project_data))

    return UpcomingProjectsResponse(projects=result, total=len(result))
```

## Implementation Plan (ETL-Integrated Name Aggregation)

### Phase 1: Update Models and ETL Enhancement (45 minutes)
1. ✅ Update SQLModel classes to include `project_name_en` in Projects table
2. ✅ Add custom transformation function `enhance_projects_with_english_names`
3. ✅ Modify ETL runner to apply custom transformations
4. ✅ Update Buildings and Units models to preserve CSV data

### Phase 2: Recreate Database and Run ETL (Normal ETL Runtime)
1. ✅ Recreate database with `--full-refresh` flag
2. ✅ ETL processes Projects.csv and enhances with English names from Units.csv
3. ✅ Buildings and Units get their project name data from their respective CSVs
4. ✅ All project name aggregation happens during ETL processing

### Phase 3: Update Application (30 minutes)
1. ✅ Update supply service to use `project_name_en` directly from projects table
2. ✅ Test supply endpoint shows English names
3. ✅ Create project explorer view for future catalog

## Benefits of ETL-Integrated Aggregation

### Clean Architecture
- ✅ **Single source of truth**: Projects table contains both Arabic and English names
- ✅ **No post-processing**: Everything happens during ETL
- ✅ **Simple queries**: Direct column access, no JOINs needed for names

### ETL Integration
- ✅ **Consistent with ETL patterns**: Uses transformation functions within ETL flow
- ✅ **Data aggregation during processing**: English names populated as Projects.csv is processed
- ✅ **Maintainable**: Custom transformation is part of ETL configuration

### Performance & Reliability  
- ✅ **Fast queries**: Direct column access instead of JOINs
- ✅ **Robust**: If Units.csv unavailable, Projects still get Arabic names
- ✅ **Incremental updates**: Works with your existing incremental ETL logic

## Expected Benefits

### For Users
- ✅ English project names on supply page
- ✅ Professional, accessible interface
- ✅ Consistent naming across all project features

### For Developers
- ✅ Clean, optimal schema design
- ✅ Rich data foundation for project catalog
- ✅ Simple, maintainable codebase
- ✅ Leverages all available CSV data

### For Business  
- ✅ Enhanced user experience
- ✅ Professional English interface
- ✅ Solid foundation for project browsing features

## Success Metrics

1. **Data Coverage**: >90% of active projects display English names
2. **ETL Performance**: Maintains current speed (~30min for full refresh)
3. **User Experience**: Supply page shows English project names
4. **Development**: Clean implementation with no migration complexity

## Next Steps

1. **Update Models**: Modify SQLModel classes to include new fields
2. **Recreate Database**: Drop and recreate with new schema
3. **Run ETL**: Import all data with new structure
4. **Populate English Names**: One UPDATE query to complete project names
5. **Update Endpoints**: Modify supply service to use English names

---

*This fresh start approach gives us the optimal database structure while maintaining the performance and reliability of your existing ETL system.*

---

*This plan ensures we have bulletproof, high-quality data that properly supports the project/unit/building explorer while maintaining data integrity and providing a clear upgrade path.*