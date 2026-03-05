import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],

	server: {
		allowedHosts: ['demo.vitevue.com']
	},

	build: {
		rollupOptions: {
			output: {
				manualChunks(id) {
					if (id.includes('node_modules/posthog-js')) return 'vendor-posthog';
					if (id.includes('node_modules/maplibre-gl')) return 'vendor-maplibre';
					if (id.includes('node_modules')) return 'vendor';
				}
			}
		}
	}
});
