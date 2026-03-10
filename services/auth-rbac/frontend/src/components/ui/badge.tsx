import React from 'react';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  /**
   * Badge variant
   * @default 'default'
   */
  variant?: 'default' | 'primary' | 'success' | 'warning' | 'error' | 'info';
  
  /**
   * Badge size
   * @default 'md'
   */
  size?: 'sm' | 'md' | 'lg';
  
  /**
   * Show dot indicator
   * @default false
   */
  dot?: boolean;
}

/**
 * Badge Component
 * 
 * Small status indicator or label component.
 * Accessible with proper contrast ratios meeting WCAG 2.1 AA standards.
 * 
 * @example
 * ```tsx
 * <Badge variant="success">Active</Badge>
 * <Badge variant="warning" dot>Pending</Badge>
 * <Badge size="lg">New Feature</Badge>
 * ```
 */
export const Badge: React.FC<BadgeProps> = ({
  variant = 'default',
  size = 'md',
  dot = false,
  className = '',
  children,
  ...props
}) => {
  const baseStyles = 'inline-flex items-center gap-1.5 font-medium rounded-full';
  
  const variantStyles = {
    default: 'bg-slate-100 text-slate-700',
    primary: 'bg-blue-100 text-blue-700',
    success: 'bg-green-100 text-green-700',
    warning: 'bg-yellow-100 text-yellow-800',
    error: 'bg-red-100 text-red-700',
    info: 'bg-blue-100 text-blue-700',
  };
  
  const sizeStyles = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-2.5 py-1 text-sm',
    lg: 'px-3 py-1.5 text-base',
  };
  
  const dotColors = {
    default: 'bg-slate-500',
    primary: 'bg-blue-500',
    success: 'bg-green-500',
    warning: 'bg-yellow-500',
    error: 'bg-red-500',
    info: 'bg-blue-500',
  };
  
  const classes = `${baseStyles} ${variantStyles[variant]} ${sizeStyles[size]} ${className}`;
  
  return (
    <span className={classes} {...props}>
      {dot && <span className={`w-1.5 h-1.5 rounded-full ${dotColors[variant]}`} aria-hidden="true" />}
      {children}
    </span>
  );
};
