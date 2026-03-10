/** @type {import('tailwindcss').Config} */
export default {
	content: ['./src/lib/**/*.{js,jsx,ts,tsx,svelte}', './src/routes/**/*.{js,jsx,ts,tsx,svelte}'],
	theme: {
		extend: {
			fontFamily: {
				sans: [
					'Inter',
					'ui-sans-serif',
					'system-ui',
					'-apple-system',
					'BlinkMacSystemFont',
					'Segoe UI',
					'Roboto',
					'Helvetica Neue',
					'Arial',
					'Noto Sans',
					'sans-serif'
				]
			},
			animation: {
				float: 'float 8s ease-in-out infinite',
				'float-delayed': 'float-delayed 10s ease-in-out infinite',
				'float-slow': 'float-slow 12s ease-in-out infinite',
				'bounce-slow': 'bounce-slow 3s ease-in-out infinite',
				'pulse-slow': 'pulse-slow 6s ease-in-out infinite'
			},
			keyframes: {
				float: {
					'0%, 100%': { transform: 'translate(0, 0) scale(1)' },
					'33%': { transform: 'translate(30px, -30px) scale(1.1)' },
					'66%': { transform: 'translate(-20px, 20px) scale(0.9)' }
				},
				'float-delayed': {
					'0%, 100%': { transform: 'translate(0, 0) scale(1)' },
					'33%': { transform: 'translate(-30px, 30px) scale(1.1)' },
					'66%': { transform: 'translate(20px, -20px) scale(0.9)' }
				},
				'float-slow': {
					'0%, 100%': { transform: 'translate(0, 0) scale(1)' },
					'50%': { transform: 'translate(40px, 40px) scale(1.15)' }
				},
				'bounce-slow': {
					'0%, 100%': { transform: 'translateY(0)', opacity: '0.4' },
					'50%': { transform: 'translateY(-20px)', opacity: '0.8' }
				},
				'pulse-slow': {
					'0%, 100%': { opacity: '0.3', transform: 'translate(-50%, -50%) scale(1)' },
					'50%': { opacity: '0.5', transform: 'translate(-50%, -50%) scale(1.05)' }
				}
			}
		}
	}
}
