import { sveltekit } from '@sveltejs/kit/vite'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],

	server: {
		allowedHosts: ['demo.vitevue.com', 'frontend', 'localhost', '127.0.0.1']
	},

	test: {
		environment: 'node',
		include: ['tests/**/*.test.ts']
	},

	build: {
		rollupOptions: {
			output: {
				manualChunks(id) {
					if (id.includes('node_modules/posthog-js')) return 'vendor-posthog'
					if (id.includes('node_modules/maplibre-gl')) return 'vendor-maplibre'
					if (id.includes('node_modules')) return 'vendor'
				}
			}
		}
	}
})
