import React, { createContext, useContext, useState, useEffect } from 'react';

type Theme = 'light' | 'dark';

interface ThemeContextType {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

/**
 * ThemeProvider Component
 * 
 * Provides theme context to the application.
 * Manages theme state and persists to localStorage.
 * 
 * @example
 * ```tsx
 * <ThemeProvider>
 *   <App />
 * </ThemeProvider>
 * ```
 */
export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setThemeState] = useState<Theme>(() => {
    // Check localStorage for saved theme preference
    const savedTheme = localStorage.getItem('theme') as Theme;
    if (savedTheme) return savedTheme;
    
    // Check system preference
    if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
    
    return 'light';
  });
  
  useEffect(() => {
    // Apply theme class to document root
    const root = window.document.documentElement;
    root.classList.remove('light', 'dark');
    root.classList.add(theme);
    
    // Save to localStorage
    localStorage.setItem('theme', theme);
  }, [theme]);
  
  const toggleTheme = () => {
    setThemeState((prev) => (prev === 'light' ? 'dark' : 'light'));
  };
  
  const setTheme = (newTheme: Theme) => {
    setThemeState(newTheme);
  };
  
  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
};

/**
 * useTheme Hook
 * 
 * Access current theme and theme controls.
 * 
 * @example
 * ```tsx
 * const { theme, toggleTheme } = useTheme();
 * 
 * <button onClick={toggleTheme}>
 *   {theme === 'light' ? 'Dark Mode' : 'Light Mode'}
 * </button>
 * ```
 */
export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};

/**
 * Dark Mode Theme Tokens (Future Implementation)
 * 
 * When dark mode is fully implemented, these tokens will be used
 * to override the default light theme colors.
 */
export const darkThemeTokens = {
  colors: {
    background: {
      primary: '#0f172a',      // slate-950
      secondary: '#1e293b',    // slate-900
      tertiary: '#334155',     // slate-700
    },
    text: {
      primary: '#f1f5f9',      // slate-100
      secondary: '#cbd5e1',    // slate-300
      tertiary: '#94a3b8',     // slate-400
    },
    border: {
      default: '#334155',      // slate-700
      subtle: '#475569',       // slate-600
    },
  },
};

/**
 * Light Mode Theme Tokens (Current Implementation)
 */
export const lightThemeTokens = {
  colors: {
    background: {
      primary: '#ffffff',      // white
      secondary: '#f8fafc',    // slate-50
      tertiary: '#f1f5f9',     // slate-100
    },
    text: {
      primary: '#0f172a',      // slate-950
      secondary: '#334155',    // slate-700
      tertiary: '#64748b',     // slate-500
    },
    border: {
      default: '#e2e8f0',      // slate-200
      subtle: '#cbd5e1',       // slate-300
    },
  },
};
