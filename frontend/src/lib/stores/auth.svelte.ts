import posthog from 'posthog-js';
import { browser } from '$app/environment';
import { auth, ApiError, type User, type UserWithInitials } from '$lib/api';

class AuthStore {
  #user = $state<UserWithInitials | null>(null);
  #loading = $state(true);
  #authenticated = $state(false);
  #identified = false;

  get user() { return this.#user; }
  get loading() { return this.#loading; }
  get authenticated() { return this.#authenticated; }
  get isAdmin() { return this.#user?.role === 'admin'; }

  async checkAuth() {
    this.#loading = true;
    try {
      const userData = await auth.me();
      const initials = `${userData.first_name?.[0] ?? ''}${userData.last_name?.[0] ?? ''}`.toUpperCase();
      this.#user = { ...userData, initials };
      this.#authenticated = true;
      
      if (browser && this.#user && !this.#identified) {
        posthog.identify(this.#user.id, {
          email: this.#user.email,
          first_name: this.#user.first_name,
          last_name: this.#user.last_name,
          organization_id: this.#user.organization_id,
          organization_name: this.#user.organization_name,
        });
        this.#identified = true;
      }
      
      return true;
    } catch (error) {
      // 401 is expected when not authenticated
      if (!(error instanceof ApiError && error.status === 401)) {
        console.error('Auth check failed:', error);
      }
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

  setUser(userData: User) {
    const initials = `${userData.first_name?.[0] ?? ''}${userData.last_name?.[0] ?? ''}`.toUpperCase();
    this.#user = { ...userData, initials };
    this.#authenticated = true;
    this.#loading = false;
    this.#identified = true; // Already identified in load function
  }

  login() {
    auth.login();
  }

  async logout() {
    try {
      await auth.logout();
    } catch (e) {
      console.error('Logout error:', e);
    }
    
    if (browser) {
      posthog.reset();
    }
    
    this.#user = null;
    this.#authenticated = false;
    this.#identified = false;
    window.location.href = '/';
  }
}

export const authStore = new AuthStore();
