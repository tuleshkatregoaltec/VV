<script lang="ts">
  import Footer from '$lib/components/layout/Footer.svelte';
</script>

<div class="h-screen bg-background flex flex-col relative">
  <main class="flex-1 flex flex-col items-center justify-center max-w-5xl mx-auto w-full px-4 relative z-10">
    <h1
      class="text-4xl sm:text-5xl md:text-6xl lg:text-7xl xl:text-8xl font-black leading-[1.2] mb-6 tracking-tight text-gray-900 text-left transition-opacity duration-300 whitespace-nowrap block"
    >
      We are building the platform<br /> that gives you the edge.
    </h1>
    <p class="text-[0.5rem] sm:text-[0.625rem] md:text-[0.625rem] lg:text-[0.75rem] xl:text-[0.875rem] text-gray-400 font-semibold mt-4 tracking-[0.1em] uppercase text-left">
      Coming January 2026
    </p>
    <div class="text-[0.375rem] sm:text-[0.5rem] md:text-[0.5rem] lg:text-[0.625rem] xl:text-[0.75rem] text-gray-400 mt-2 select-all text-left">
      contact@vitevue.com
    </div>
  </main>

  <Footer></Footer>
</div>

