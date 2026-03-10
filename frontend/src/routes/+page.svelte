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
	<style>
		html {
			scroll-behavior: smooth;
		}
	</style>
</svelte:head>

<div class="min-h-screen bg-background">
	<FloatingNavbar />
	<HeroSection />
	<PreviewSection />
	<PersonasSection />
	<PricingSection />
	<FinalCTA />
	<Footer />
</div>
