import React from 'react';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /**
   * Card variant
   * @default 'default'
   */
  variant?: 'default' | 'bordered' | 'elevated';
  
  /**
   * Padding size
   * @default 'md'
   */
  padding?: 'none' | 'sm' | 'md' | 'lg';
  
  /**
   * Hover effect
   * @default false
   */
  hoverable?: boolean;
}

export interface CardHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
  /**
   * Title element
   */
  title?: React.ReactNode;
  
  /**
   * Subtitle element
   */
  subtitle?: React.ReactNode;
  
  /**
   * Action element (e.g., button)
   */
  action?: React.ReactNode;
}

export interface CardFooterProps extends React.HTMLAttributes<HTMLDivElement> {}

/**
 * Card Component
 * 
 * Container component for grouping related content.
 * Accessible with proper semantic HTML structure.
 * 
 * @example
 * ```tsx
 * <Card>
 *   <CardHeader title="Card Title" subtitle="Description" />
 *   <CardContent>Content goes here</CardContent>
 *   <CardFooter>Footer content</CardFooter>
 * </Card>
 * ```
 */
export const Card: React.FC<CardProps> = ({
  variant = 'default',
  padding = 'md',
  hoverable = false,
  className = '',
  children,
  ...props
}) => {
  const variantStyles = {
    default: 'bg-white border border-slate-200',
    bordered: 'bg-white border-2 border-slate-300',
    elevated: 'bg-white shadow-md',
  };
  
  const paddingStyles = {
    none: '',
    sm: 'p-4',
    md: 'p-6',
    lg: 'p-8',
  };
  
  const hoverStyles = hoverable ? 'transition-shadow hover:shadow-lg cursor-pointer' : '';
  
  const classes = `${variantStyles[variant]} ${paddingStyles[padding]} ${hoverStyles} rounded-lg ${className}`;
  
  return (
    <div className={classes} {...props}>
      {children}
    </div>
  );
};

/**
 * CardHeader Component
 * 
 * Header section for Card component.
 */
export const CardHeader: React.FC<CardHeaderProps> = ({
  title,
  subtitle,
  action,
  className = '',
  children,
  ...props
}) => {
  return (
    <div className={`flex items-start justify-between mb-4 ${className}`} {...props}>
      <div className="flex-1 min-w-0">
        {title && (
          <h3 className="text-lg font-semibold text-slate-900">
            {title}
          </h3>
        )}
        {subtitle && (
          <p className="text-sm text-slate-600 mt-1">
            {subtitle}
          </p>
        )}
        {children}
      </div>
      {action && (
        <div className="flex-shrink-0 ml-4">
          {action}
        </div>
      )}
    </div>
  );
};

/**
 * CardContent Component
 * 
 * Main content section for Card component.
 */
export const CardContent: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className = '',
  children,
  ...props
}) => {
  return (
    <div className={className} {...props}>
      {children}
    </div>
  );
};

/**
 * CardFooter Component
 * 
 * Footer section for Card component.
 */
export const CardFooter: React.FC<CardFooterProps> = ({
  className = '',
  children,
  ...props
}) => {
  return (
    <div className={`mt-4 pt-4 border-t border-slate-200 ${className}`} {...props}>
      {children}
    </div>
  );
};
