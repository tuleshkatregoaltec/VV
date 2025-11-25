interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
}

class AuthStore {
  #user = $state<User | null>(null);
  #loading = $state(true);
  #authenticated = $state(false);

  get user() { return this.#user; }
  get loading() { return this.#loading; }
  get authenticated() { return this.#authenticated; }

  async checkSession() {
    this.#loading = true;
    try {
      const res = await fetch('http://localhost:8000/api/auth/session', {
        credentials: 'include'
      });
      
      if (res.ok) {
        const data = await res.json();
        this.#user = data.user;
        this.#authenticated = true;
      } else {
        this.#user = null;
        this.#authenticated = false;
      }
    } catch (error) {
      console.error('Session check failed:', error);
      this.#authenticated = false;
    } finally {
      this.#loading = false;
    }
  }

  login() {
    window.location.href = 'http://localhost:8000/auth/login';
  }

  async logout() {
    window.location.href = 'http://localhost:8000/auth/logout';
  }
}

export const authStore = new AuthStore();
