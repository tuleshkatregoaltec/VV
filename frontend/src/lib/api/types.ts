export interface Transaction {
    transaction_id: string;
    project_name_en: string | null;
    building_name_en: string | null;
    property_type_en: string | null;
    property_sub_type_en: string | null;
    rooms_en: string | null;
    procedure_area: number | null;
    actual_worth: number | null;
    meter_sale_price: number | null;
    reg_type_en: string | null;
    instance_date: string | null;
    area_name_en: string | null;
}

export interface TransactionListResponse {
    transactions: Transaction[];
    total: number;
    limit: number;
    offset: number;
}

export interface RentalContract {
    contract_id: string;
    project_name_en: string | null;
    ejari_property_type_en: string | null;
    ejari_property_sub_type_en: string | null;
    tenant_type_en: string | null;
    actual_area: number | null;
    annual_amount: number | null;
    contract_reg_type_en: string | null;
    contract_start_date: string | null;
    area_name_en: string | null;
}

export interface RentalContractListResponse {
    contracts: RentalContract[];
    total: number;
    limit: number;
    offset: number;
}

export interface FilterOptions {
    projects: string[];
    buildings: string[];
    property_types: string[];
    property_sub_types: string[];
    master_projects: string[];
    rooms: string[];
    registration_types: string[];
    // Rental-specific
    tenant_types?: string[];
    contract_reg_types?: string[];
}
