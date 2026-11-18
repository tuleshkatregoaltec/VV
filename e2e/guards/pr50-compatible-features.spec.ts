import { expect, test } from '../fixtures/guards';

const captured = '2026-05-27T12:00:00Z';
const listing = {
    listing_id: 'compatible-1', listing_mode: 'sale', asset_class: 'residential',
    title: 'Synthetic valuation apartment', price_value: 1800000, price_currency: 'AED',
    price_period: null, price_per_sqft_aed: 1500, bedrooms: '2', bathrooms: '2',
    property_type: 'Apartment', size_value: 1200, size_unit: 'sqft',
    tower_name: 'Synthetic Tower', subcommunity_name: 'Synthetic Project',
    area_name: 'Synthetic Area', city_name: 'Dubai', location_name: 'Synthetic Area',
    captured_at: captured, listed_date: '2026-04-01', listing_age_days: 56,
    is_available: true, is_verified: true, comparable_count: 5,
    market_position: 'below_market', market_delta_pct: -0.1,
    market_estimate_aed: 2000000, market_median_price_per_sqft_aed: 1667,
    benchmark_level: 'building_layout', urgency_signal: 'none', urgency_terms: [],
    valuation_method: 'dld_sales', estimated_value_aed: 2000000,
    estimated_value_low_aed: 1900000, estimated_value_high_aed: 2100000,
    valuation_confidence: 'high', value_gap_pct: -0.1, is_off_plan: false,
    valued_at: '2026-11-17', broker_name: 'Synthetic Brokerage', share_url: 'javascript:alert(1)',
    valuation_comparables: [{ date: '2026-10-15', unit: '1203', size_sqft: 1200, price_aed: 2000000, psf: 1667 }]
};
const property = {
    property_key: 'synthetic|1203', building_name: 'Synthetic Tower', project_name: '',
    area_name: 'Synthetic Area', unit_number: '1203', property_type: 'Apartment',
    ownership_status: 'verified_current_owner', confidence_score: 98, match_reason: '',
    source_lists: [], source_rows: [], estimated_value_aed: 2000000,
    estimated_value_low_aed: 1900000, estimated_value_high_aed: 2100000,
    valuation_confidence: 'high', valued_at: '2026-11-17'
};
const owner = {
    owner_key: 'synthetic-owner', contact_name: 'Synthetic Owner', property_count: 1,
    total_property_count: 1, current_property_count: 1,
    highest_ownership_status: 'verified_current_owner', properties: [property]
};

test.beforeEach(async ({ page, usePersona }) => {
    await usePersona('active-owner');
    await page.route('**/api/v1/**', async route => {
        const url = new URL(route.request().url());
        if (url.pathname === '/api/v1/auth/me') return route.fallback();
        let body: unknown = [];
        if (url.pathname === '/api/v1/listings') body = {
            listings: [{ ...listing, listing_mode: url.searchParams.get('mode') ?? 'rent' }],
            total: 1, limit: 40, offset: 0, filters: {}, data_as_of: captured
        };
        if (url.pathname === '/api/v1/listings/compatible-1') body = listing;
        if (url.pathname === '/api/v1/listings/filters') body = { areas: ['Synthetic Area'], property_types: ['Apartment'], bedrooms: ['2'] };
        if (url.pathname === '/api/v1/listings/analytics') body = {
            total: 1, median_price_aed: 1800000, median_price_per_sqft_aed: 1500,
            average_listing_age_days: 56, median_listing_age_days: 56, newly_listed_30d: 0,
            below_market_count: 1, near_market_count: 0, above_market_count: 0,
            benchmarked_count: 1, snapshot_at: captured, trend: []
        };
        if (url.pathname === '/api/v1/crm/inbound/enquiries') body = { enquiries: [], total: 0, summary: {} };
        if (url.pathname === '/api/v1/crm/owner-registry') body = { owners: [owner], total: 1 };
        if (url.pathname === '/api/v1/crm/owners/synthetic-owner') body = owner;
        if (url.pathname === '/api/v1/crm/renewals') {
            const known = url.searchParams.get('owner') === 'known';
            body = { leads: known ? [{ lead_id: 'lease-event', unit_candidate_key: 'unit-key', building_name: 'Synthetic Tower', unit_number: '1203', area_name: 'Synthetic Area', annual_rent_aed: 120000, days_to_expiry: 10, property_type: 'Apartment' }] : [],
                owners: known ? { 'unit-key': { name: 'Resolved Owner', phone: '+971500000001', source: 'owner_import' } } : {}, total: known ? 1 : 0, property_types: [], projects: [], buildings: [] };
        }
        await route.fulfill({ json: body });
    });
});

// Google Calendar was restored (guards/crm-calendar-email.spec.ts); the email and WhatsApp PR 50
// prototypes stay redirects to the connector preview.
for (const connector of ['email', 'whatsapp']) {
    test(`unfinished ${connector} prototype URL opens only the connector preview`, async ({ page }) => {
        const prototypeCalls: string[] = [];
        page.on('request', request => {
            if (/\/api\/v1\/crm\/(email|whatsapp|assistant)(?:\/|\?|$)/.test(request.url())) prototypeCalls.push(request.url());
        });
        await page.goto(`/crm/connectors/${connector}`);
        await expect(page).toHaveURL(/\/crm\/connectors$/);
        await expect(page.getByText('Provider connections are simulated.', { exact: false })).toBeVisible();
        await expect(page.getByRole('link', { name: 'Connect WhatsApp', exact: true })).toHaveAttribute('href', '/crm/whatsapp');
        expect(prototypeCalls).toEqual([]);
    });
}

test('sale valuation and bargain filtering retain capture disclosure and safe source links', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/listings');
    await page.getByRole('button', { name: 'For sale', exact: true }).click();
    await expect(page.getByText('Sales behind the estimate', { exact: true })).toBeVisible();
    await expect(page.getByText('5 recorded sales · high confidence', { exact: false }).first()).toBeVisible();
    await expect(page.getByRole('region', { name: 'Listing data snapshot' })).toContainText('not a live feed');
    await expect(page.getByRole('link', { name: 'Source record' })).toHaveCount(0);
    const request = page.waitForRequest(req => {
        const url = new URL(req.url());
        return url.pathname === '/api/v1/listings' && url.searchParams.get('market_position') === 'below_market' && url.searchParams.get('sort') === 'value_gap';
    });
    await page.getByRole('button', { name: 'Possible bargains', exact: true }).click();
    await request;
    await expect(page.getByRole('heading', { name: 'Possible bargains', exact: true })).toBeVisible();
    expect(errors).toEqual([]);
});

test('owner estimate keeps ownership history and provenance controls', async ({ page }) => {
    await page.goto('/crm/owners');
    await page.getByRole('button', { name: 'Synthetic Owner', exact: true }).click();
    await page.getByRole('button', { name: '#1203', exact: false }).click();
    await expect(page.getByText('Vitevue estimate · high confidence · 17 Nov 2026', { exact: true })).toBeVisible();
    await expect(page.getByText('AED 2,000,000 · range 1.9m–2.1m', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Show ownership history' })).toBeVisible();
});

test('renewal owner toggle preserves server filtering', async ({ page }) => {
    await page.goto('/crm/assets');
    await page.getByRole('tab', { name: 'Renewals', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Owner known', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByText('Resolved Owner · +971500000001', { exact: true })).toBeVisible();
    const request = page.waitForRequest(req => {
        const url = new URL(req.url());
        return url.pathname === '/api/v1/crm/renewals' && url.searchParams.get('owner') === 'unknown';
    });
    await page.getByRole('button', { name: 'Owner unknown', exact: true }).click();
    await request;
    await expect(page.getByText('Resolved Owner', { exact: false })).toHaveCount(0);
    await expect(page.getByText('No leases match these filters.', { exact: true })).toBeVisible();
});

test('older APIs keep normal listings and renewals without unsupported feature requests', async ({ page }) => {
    const listingRequests: URL[] = [];
    const renewalRequests: URL[] = [];
    const { valuation_method, ...legacyListing } = listing;
    await page.route('**/api/v1/listings?*', route => {
        const url = new URL(route.request().url());
        listingRequests.push(url);
        return route.fulfill({ json: { listings: [legacyListing], total: 1, limit: 40, offset: 0, filters: {} } });
    });
    await page.goto('/listings');
    await page.getByRole('button', { name: 'For sale', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Possible bargains', exact: true })).toHaveCount(0);
    expect(listingRequests.every(url => !url.searchParams.has('sort') && !url.searchParams.has('market_position'))).toBe(true);
    await page.route('**/api/v1/crm/renewals?*', route => {
        renewalRequests.push(new URL(route.request().url()));
        return route.fulfill({ json: { leads: [], total: 0 } });
    });
    await page.goto('/crm/assets');
    await page.getByRole('tab', { name: 'Renewals', exact: true }).click();
    await expect(page.getByText('No leases match these filters.', { exact: true })).toBeVisible();
    await expect(page.getByRole('group', { name: 'Owner', exact: true })).toHaveCount(0);
    expect(renewalRequests.length).toBeGreaterThan(0);
    expect(renewalRequests.every(url => !url.searchParams.has('owner'))).toBe(true);
});
