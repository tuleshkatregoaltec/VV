/** @type {import('tailwindcss').Config} */
export default {
	content: ['./src/lib/**/*.{js,jsx,ts,tsx,svelte}', './src/routes/**/*.{js,jsx,ts,tsx,svelte}'],
	theme: {
		extend: {
			fontFamily: {
				sans: [
					'General Sans',
					'ui-sans-serif',
					'system-ui',
					'-apple-system',
					'Segoe UI',
					'Roboto',
					'Helvetica Neue',
					'Arial',
					'Noto Sans',
					'sans-serif'
				],
				display: ['Fraunces', 'General Sans', 'ui-serif', 'Georgia', 'serif']
			}
		}
	}
}
