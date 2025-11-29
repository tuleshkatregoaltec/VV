interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  organisation_id: string;
  organisation_name: string;
}

class AuthStore {
  #user = $state<User | null>(null);
  #loading = $state(true);
  #authenticated = $state(false);

  get user() { return this.#user; }
  get loading() { return this.#loading; }
  get authenticated() { return this.#authenticated; }

  async checkAuth() {
    this.#loading = true;
    try {
      const res = await fetch('http://localhost:8000/auth/me', {
        credentials: 'include'
      });
      
      if (res.ok) {
        this.#user = await res.json();
        this.#authenticated = true;
        return true;
      } else {
        this.#user = null;
        this.#authenticated = false;
        return false;
      }
    } catch (error) {
      console.error('Auth check failed:', error);
      this.#user = null;
      this.#authenticated = false;
      return false;
    } finally {
      this.#loading = false;
    }
  }

  setLoading(loading: boolean) {
    this.#loading = loading;
  }

  login() {
    window.location.href = 'http://localhost:8000/auth/login';
  }

  async logout() {
    try {
      await fetch('http://localhost:8000/auth/logout', {
        method: 'POST',
        credentials: 'include'
      });
    } catch (e) {
      console.error('Logout error:', e);
    }
    this.#user = null;
    this.#authenticated = false;
    window.location.href = '/';
  }
}

export const authStore = new AuthStore();
