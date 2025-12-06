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
    master_project?: string;
}

function buildQuery(params: AnalyticsParams): string {
    const query = new URLSearchParams();
    if (params.property_usage) query.append('property_usage', params.property_usage);
    if (params.timeframe_days) query.append('timeframe_days', String(params.timeframe_days));
    if (params.master_project && params.master_project !== 'All') query.append('master_project', params.master_project);
    return query.toString();
}

export const analytics = {
    sales: (params: AnalyticsParams = {}) =>
        api<SalesAnalyticsResponse>(`/api/v1/analytics/sales?${buildQuery(params)}`),

    rentals: (params: AnalyticsParams = {}) =>
        api<RentalAnalyticsResponse>(`/api/v1/analytics/rentals?${buildQuery(params)}`),
};
