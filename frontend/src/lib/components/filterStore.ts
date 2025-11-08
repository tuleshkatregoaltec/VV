import { writable } from 'svelte/store';

export const propertyType = writable<string>('Residential');
export const area = writable<string>('Dubai Marina');
export const timeframe = writable<string>('Last Month');
