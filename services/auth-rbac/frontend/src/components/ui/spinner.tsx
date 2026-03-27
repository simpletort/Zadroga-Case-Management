import React from 'react';

export interface SpinnerProps {
  /**
   * Spinner size
   * @default 'md'
   */
  size?: 'sm' | 'md' | 'lg' | 'xl';
  
  /**
   * Spinner variant
   * @default 'primary'
   */
  variant?: 'primary' | 'secondary' | 'white';
  
  /**
   * Screen reader label
   * @default 'Loading...'
   */
  label?: string;
}

/**
 * Spinner Component
 * 
 * Loading spinner with accessibility support.
 * Meets WCAG 2.1 AA standards with proper ARIA attributes.
 * 
 * @example
 * ```tsx
 * <Spinner />
 * <Spinner size="lg" variant="white" label="Loading data..." />
 * ```
 */
export const Spinner: React.FC<SpinnerProps> = ({
  size = 'md',
  variant = 'primary',
  label = 'Loading...',
}) => {
  const sizeStyles = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-8 h-8',
    xl: 'w-12 h-12',
  };
  
  const variantStyles = {
    primary: 'border-blue-600',
    secondary: 'border-purple-600',
    white: 'border-white',
  };
  
  return (
    <div
      role="status"
      aria-label={label}
      className="inline-flex items-center justify-center"
    >
      <div
        className={`${sizeStyles[size]} border-2 border-t-transparent rounded-full animate-spin ${variantStyles[variant]}`}
      />
      <span className="sr-only">{label}</span>
    </div>
  );
};
