import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");


interface HybridComboboxProps {
  value: string;
  onChange: (val: string) => void;
  placeholder?: string;
  className?: string;
}

export function HybridCombobox({ value, onChange, placeholder = "Select or type entity...", className = "" }: HybridComboboxProps) {
  const [entities, setEntities] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchEntities() {
      try {
        // Pird: include cookie so the auth-gated endpoint accepts the request.
        // See handoffs/dubbing-security-pass2-fixes.md Fix 6.
        const res = await fetch(`${API_BASE}/video/manual/entities`, { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          setEntities(data.entities || []);
        }
      } catch (err) {
        console.error("Failed to fetch entities", err);
      } finally {
        setLoading(false);
      }
    }
    fetchEntities();
  }, []);

  return (
    <div className={`relative ${className}`}>
      <input
        list="entity-suggestions"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={loading ? "Loading entities..." : placeholder}
        disabled={loading}
        className="w-full px-3 py-2 bg-white/[0.04] border border-white/[0.08] rounded-xl text-sm text-white placeholder-ink-400 focus:outline-none focus:border-brand-400 transition-colors"
      />
      <datalist id="entity-suggestions">
        {entities.map(entity => (
          <option key={entity} value={entity} />
        ))}
      </datalist>
    </div>
  );
}
