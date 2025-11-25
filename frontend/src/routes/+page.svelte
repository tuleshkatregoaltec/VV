<script lang="ts">
  import Footer from '$lib/components/layout/Footer.svelte';
</script>

<div class="h-full bg-background flex flex-col relative">
  <main class="flex-1 flex flex-col items-center justify-center max-w-5xl mx-auto w-full px-4 relative z-10">
    <h1
      class="text-[clamp(2.5rem,8vw,6rem)] font-black leading-[1.2] mb-6 tracking-tight text-gray-900 text-left transition-opacity duration-300 whitespace-nowrap block"
    >
      We are building the platform<br /> that gives you the edge.
  </h1>
  <p class="text-base text-gray-400 font-semibold mt-4 tracking-widest uppercase text-left">Coming January 2026</p>
  <div class="text-sm text-gray-400 mt-2 select-all text-left">contact@vitevue.com</div>
  </main>

  <Footer></Footer>
</div>

