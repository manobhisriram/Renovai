import { create } from "zustand";
import type { User } from "../types";

const KEY = "renovai.session";
interface Session { token: string; user: User }

function load(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

interface AuthState {
  token: string | null;
  user: User | null;
  signIn: (token: string, user: User) => void;
  signOut: () => void;
}

export const useAuth = create<AuthState>((set) => {
  const s = load();
  return {
    token: s?.token ?? null,
    user: s?.user ?? null,
    signIn: (token, user) => {
      sessionStorage.setItem(KEY, JSON.stringify({ token, user }));
      set({ token, user });
    },
    signOut: () => {
      sessionStorage.removeItem(KEY);
      set({ token: null, user: null });
    },
  };
});
