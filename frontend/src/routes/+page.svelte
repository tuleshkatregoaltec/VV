<script lang="ts">
  import Footer from '$lib/components/Footer.svelte';
  import WaitlistModal from '$lib/components/waitlist/WaitlistModal.svelte';
  import { fly } from 'svelte/transition';

  let showModal = false;
  let initialEmail = '';
  let triggerElement: HTMLInputElement;

  function openModal() {
    showModal = true;
  }

  function closeModal() {
    showModal = false;
  }
</script>

<div class="h-full bg-background flex flex-col relative">
  <main class="flex-1 flex flex-col items-center justify-start max-w-5xl mx-auto w-full px-4 relative z-10 pt-12" class:opacity-30={showModal} class:pointer-events-none={showModal}>
    <h1
      class="text-[clamp(2.5rem,8vw,6rem)] font-black leading-[1.2] mb-6 tracking-tight text-gray-900 text-left transition-opacity duration-300"
    >
      Unlock real-world<br /> market insights.
    </h1>
    <div class="w-full max-w-lg">
      <input 
        bind:this={triggerElement}
        type="email"
        placeholder="Enter your email"
        on:click={openModal}
        readonly
        class="w-full px-6 py-4 rounded-lg border border-gray-300 text-gray-900 placeholder-gray-500 cursor-pointer hover:border-gray-400 transition-all focus:outline-none"
        class:opacity-0={showModal}
      />
    </div>
  </main>

  <Footer></Footer>

  {#if showModal}
    <div class="fixed inset-0 z-[99]" transition:fly={{ y: 0, duration: 0 }}>
      <WaitlistModal {initialEmail} onClose={closeModal} />
    </div>
  {/if}
</div>

