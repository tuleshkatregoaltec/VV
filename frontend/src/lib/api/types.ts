export interface Transaction {
    transaction_id: string;
    project_name: string | null;
    building_name: string | null;
    property_type: string | null;
    property_sub_type: string | null;
    rooms_description: string | null;
    procedure_area: number | null;
    actual_worth: number | null;
    meter_sale_price: number | null;
    reg_type: string | null;
    instance_date: string | null;
    area_name: string | null;
}

export interface TransactionListResponse {
    transactions: Transaction[];
    total: number;
    limit: number;
    offset: number;
}

export interface FilterOptions {
    projects: string[];
    buildings: string[];
    property_types: string[];
    property_sub_types: string[];
    rooms: string[];
    registration_types: string[];
}
