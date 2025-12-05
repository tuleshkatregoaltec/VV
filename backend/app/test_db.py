import asyncio
from sqlalchemy import text
from sqlmodel import select
from sqlalchemy.orm import selectinload  # <--- IMPORT THIS
from backend.app.db.session import get_db_session
from backend.app.db.models import Transaction, Area


async def test_comprehensive_relationships():
    print("🔄 Connecting to DB...")

    async for session in get_db_session():
        try:
            # ======================================================
            # TEST 1: Many-to-One (Transaction -> Area) - FIXED
            # ======================================================
            print("\n🔗 TEST 1: Testing Transaction -> Area (Eager Loading)")

            # FIX: Add .options(selectinload(...)) to fetch the relationship
            stmt = (
                select(Transaction)
                .options(selectinload(Transaction.area))  # type: ignore # <--- Load 'area' now
                .where(Transaction.area_id is not None)
                .limit(1)
            )

            result = await session.exec(stmt)
            txn = result.first()

            if not txn:
                print("   ⚠️ No transactions found.")
            else:
                print(f"   ✅ Found Transaction: {txn.transaction_id}")
                # Now this access is safe because data is already in memory
                if txn.area:
                    print(f"      🔗 Area loaded: {txn.area.name_en}")
                else:
                    print("      ❌ Area is None (Data integrity issue?)")

            # ======================================================
            # TEST 2: One-to-Many (Area -> Transactions) - FIXED
            # ======================================================
            print("\n🔗 TEST 2: Testing Area -> Transactions (Reverse Load)")

            if txn and txn.area_id:
                # FIX: Load transactions list eagerly
                stmt_area = (
                    select(Area)
                    .options(selectinload(Area.transactions))  # type: ignore # <--- Load children
                    .where(Area.area_id == txn.area_id)
                )
                result_area = await session.exec(stmt_area)
                area = result_area.first()

                if area:
                    print(f"   ✅ Loaded Area: {area.name_en}")
                    # Safe access
                    print(f"      🔗 Has {len(area.transactions)} transactions linked.")

            # ======================================================
            # TEST 3: Dashboard Index (Raw SQL) - FIXED
            # ======================================================
            print("\n⚡ TEST 3: Dashboard Index Check")
            check_query = text("""
                EXPLAIN (FORMAT JSON) 
                SELECT * FROM transactions 
                WHERE property_usage = 'Residential' 
                ORDER BY instance_date DESC 
                LIMIT 10
            """)
            # FIX: Use session.execute for Raw SQL
            explain_result = await session.execute(check_query)
            plan_row = explain_result.first()

            # Check if plan_row is not None BEFORE accessing [0]
            if plan_row is not None:
                # Safely access index 0 now
                plan_json_str = str(plan_row[0])

                if "idx_transactions_date_usage" in plan_json_str:
                    print("   ✅ SUCCESS: Index is working!")
                else:
                    print(f"   ⚠️ Index warning. Plan: {plan_json_str[:100]}...")
            else:
                print("   ❌ ERROR: EXPLAIN returned no rows (very unexpected).")

        except Exception as e:
            print(f"❌ ERROR: {e}")
            import traceback

            traceback.print_exc()
        break


if __name__ == "__main__":
    asyncio.run(test_comprehensive_relationships())
