import { createContext, useContext, useEffect, useState, useCallback } from "react";
import api, { setToken, getToken } from "@/lib/api";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);      // null = loading, false = anon
  const [menus, setMenus] = useState([]);
  const [permissions, setPermissions] = useState([]);
  const [dataScope, setDataScope] = useState("OWN");

  const loadMenus = useCallback(async () => {
    const { data } = await api.get("/auth/menus");
    setMenus(data.menus);
    setPermissions(data.permissions);
    setDataScope(data.data_scope);
  }, []);

  const bootstrap = useCallback(async () => {
    if (!getToken()) { setUser(false); return; }
    try {
      const { data } = await api.get("/auth/me");
      await loadMenus();          // menus ready BEFORE user is set (guards depend on it)
      setUser(data.user);
    } catch {
      setToken(null);
      setUser(false);
    }
  }, [loadMenus]);

  useEffect(() => { bootstrap(); }, [bootstrap]);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    setToken(data.access_token);
    await loadMenus();
    setUser(data.user);
    return data.user;
  };

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch {}
    setToken(null);
    setUser(false);
    setMenus([]); setPermissions([]);
  };

  const can = useCallback((perm) => permissions.includes(perm), [permissions]);

  return (
    <AuthContext.Provider value={{ user, menus, permissions, dataScope, login, logout, can }}>
      {children}
    </AuthContext.Provider>
  );
}
