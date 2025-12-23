// src/lib/api/analytics.ts
import { api } from './client';

export type TimeframeDays = 7 | 30 | 90 | 180 | 365;

export interface AnalyticsSummary {
    transaction_count: number;
    total_volume: number;
    avg_price: number;
    avg_price_sqft: number;
    min_price: number;
    max_price: number;
    volume_change_pct: number | null;
    count_change_pct: number | null;
}

export interface RentalSummary {
    contract_count: number;
    total_annual_value: number;
    avg_annual_rent: number;
    avg_rent_sqft: number;
    min_annual_rent: number;
    max_annual_rent: number;
    value_change_pct: number | null;
    count_change_pct: number | null;
}

export interface DimensionBreakdown {
    dimension_value: string;
    transaction_count: number;
    total_volume: number;
    avg_price_sqft: number;
    pct_of_total: number | null;
}

export interface RentalDimensionBreakdown {
    dimension_value: string;
    contract_count: number;
    total_annual_value: number;
    avg_rent_sqft: number;
    pct_of_total: number | null;
}

export interface TrendPoint {
    date: string;
    count: number;
    total_value: number;
    avg_value: number;
    avg_sqft: number;
}

export interface SalesAnalyticsResponse {
    timeframe_days: number;
    property_usage: string;
    summary: AnalyticsSummary;
    trends: TrendPoint[];
    by_property_type: DimensionBreakdown[];
    by_rooms: DimensionBreakdown[];
    by_reg_type: DimensionBreakdown[];
    by_master_project: DimensionBreakdown[];
}

export interface RentalAnalyticsResponse {
    timeframe_days: number;
    property_usage: string;
    summary: RentalSummary;
    trends: TrendPoint[];
    by_property_type: RentalDimensionBreakdown[];
    by_master_project: RentalDimensionBreakdown[];
}

export interface AnalyticsParams {
    property_usage?: string;
    timeframe_days?: TimeframeDays;
    start_date?: string;
    end_date?: string;
    master_project?: string;
    property_type?: string;
    rooms?: string;
    reg_type?: string;
    price_bucket?: string;
    area_bucket?: string;
}

export interface RentalAnalyticsParams {
    property_usage?: string;
    timeframe_days?: TimeframeDays;
    start_date?: string;
    end_date?: string;
    master_project?: string;
    property_type?: string;
    rent_bucket?: string;
    area_bucket?: string;
}

function buildQuery(params: AnalyticsParams | RentalAnalyticsParams): string {
    const query = new URLSearchParams();

    // Basic filters
    if (params.property_usage) query.append('property_usage', params.property_usage);

    // Date range filters (prefer explicit dates over timeframe_days)
    if (params.start_date) query.append('start_date', params.start_date);
    if (params.end_date) query.append('end_date', params.end_date);
    if (params.timeframe_days && !params.start_date) {
        query.append('timeframe_days', String(params.timeframe_days));
    }

    // Dimension filters
    if (params.master_project && params.master_project !== 'All') {
        query.append('master_project', params.master_project);
    }
    if (params.property_type) query.append('property_type', params.property_type);
    if (params.area_bucket) query.append('area_bucket', params.area_bucket);

    // Sales-specific filters
    if ('rooms' in params && params.rooms) {
        query.append('rooms', params.rooms);
    }
    if ('reg_type' in params && params.reg_type) {
        query.append('reg_type', params.reg_type);
    }
    if ('price_bucket' in params && params.price_bucket) {
        query.append('price_bucket', params.price_bucket);
    }

    // Rental-specific filters
    if ('rent_bucket' in params && params.rent_bucket) {
        query.append('rent_bucket', params.rent_bucket);
    }

    return query.toString();
}

export const analytics = {
    sales: (params: AnalyticsParams = {}) =>
        api<SalesAnalyticsResponse>(`/api/v1/analytics/sales?${buildQuery(params)}`),

    rentals: (params: RentalAnalyticsParams = {}) =>
        api<RentalAnalyticsResponse>(`/api/v1/analytics/rentals?${buildQuery(params)}`),
};
