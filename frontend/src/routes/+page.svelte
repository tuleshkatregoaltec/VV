<script lang="ts">
import FinalCTA from '$lib/components/landing/FinalCTA.svelte'
import FloatingNavbar from '$lib/components/landing/FloatingNavbar.svelte'
import HeroSection from '$lib/components/landing/HeroSection.svelte'
import PersonasSection from '$lib/components/landing/PersonasSection.svelte'
import PreviewSection from '$lib/components/landing/PreviewSection.svelte'
import PricingSection from '$lib/components/landing/PricingSection.svelte'
import Footer from '$lib/components/layout/Footer.svelte'
</script>

<svelte:head>
	<title>Vitevue - Dubai Real Estate Intelligence Platform</title>
	<meta
		name="description"
		content="Make faster, smarter decisions with AI-powered real estate intelligence. Trusted by brokers, investors, and consultants across Dubai."
	/>
	<meta property="og:title" content="Vitevue - Dubai Real Estate Intelligence Platform" />
	<meta
		property="og:description"
		content="AI-native market intelligence, transaction analytics, and evidence packs for Dubai real estate teams."
	/>
	<meta property="og:image" content="/images/vitevue-og-image-1200x630.png" />
	<meta name="twitter:image" content="/images/vitevue-twitter-card-1200x600.png" />
	<style>
		html {
			scroll-behavior: smooth;
		}
	</style>
</svelte:head>

<div class="theme-light min-h-screen bg-bone">
	<FloatingNavbar />
	<HeroSection />
	<PreviewSection />
	<PersonasSection />
	<PricingSection />
	<FinalCTA />
	<Footer />
</div>
