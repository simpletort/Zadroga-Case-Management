import React from 'react';

export interface ProgressProps {
  /**
   * Progress value (0-100)
   */
  value: number;
  
  /**
   * Progress size
   * @default 'md'
   */
  size?: 'sm' | 'md' | 'lg';
  
  /**
   * Progress variant
   * @default 'primary'
   */
  variant?: 'primary' | 'success' | 'warning' | 'error';
  
  /**
   * Show label with percentage
   * @default false
   */
  showLabel?: boolean;
  
  /**
   * Custom label
   */
  label?: string;
  
  /**
   * Indeterminate/loading state
   * @default false
   */
  indeterminate?: boolean;
}

/**
 * Progress Component
 * 
 * Accessible progress bar with ARIA attributes.
 * Meets WCAG 2.1 AA standards.
 * 
 * @example
 * ```tsx
 * <Progress value={75} showLabel />
 * <Progress value={50} variant="success" label="Uploading..." />
 * <Progress indeterminate />
 * ```
 */
export const Progress: React.FC<ProgressProps> = ({
  value,
  size = 'md',
  variant = 'primary',
  showLabel = false,
  label,
  indeterminate = false,
}) => {
  const clampedValue = Math.min(100, Math.max(0, value));
  
  const sizeStyles = {
    sm: 'h-1',
    md: 'h-2',
    lg: 'h-3',
  };
  
  const variantStyles = {
    primary: 'bg-blue-600',
    success: 'bg-green-600',
    warning: 'bg-yellow-500',
    error: 'bg-red-600',
  };
  
  return (
    <div className="w-full">
      {(showLabel || label) && (
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-slate-700">
            {label || `${clampedValue}%`}
          </span>
          {showLabel && !label && (
            <span className="text-sm text-slate-600">{clampedValue}%</span>
          )}
        </div>
      )}
      
      <div
        className={`w-full bg-slate-200 rounded-full overflow-hidden ${sizeStyles[size]}`}
        role="progressbar"
        aria-valuenow={indeterminate ? undefined : clampedValue}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label || `Progress: ${clampedValue}%`}
      >
        <div
          className={`h-full ${variantStyles[variant]} transition-all duration-300 ${
            indeterminate ? 'animate-pulse' : ''
          }`}
          style={{ width: indeterminate ? '100%' : `${clampedValue}%` }}
        />
      </div>
    </div>
  );
};
