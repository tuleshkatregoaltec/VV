<script lang="ts">
	import HeroSection from '$lib/components/landing/HeroSection.svelte';
	import BenefitsSection from '$lib/components/landing/BenefitsSection.svelte';
	import PersonasSection from '$lib/components/landing/PersonasSection.svelte';
	import PreviewSection from '$lib/components/landing/PreviewSection.svelte';
	import WhyVitevueSection from '$lib/components/landing/WhyVitevueSection.svelte';
	import FinalCTA from '$lib/components/landing/FinalCTA.svelte';
	import Footer from '$lib/components/layout/Footer.svelte';
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
	<HeroSection />
	<PreviewSection />
	<BenefitsSection />
	<PersonasSection />
	<WhyVitevueSection />
	<FinalCTA />
	<Footer />
</div>
