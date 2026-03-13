import React from 'react';

export interface DividerProps {
  /**
   * Divider orientation
   * @default 'horizontal'
   */
  orientation?: 'horizontal' | 'vertical';
  
  /**
   * Label to display in divider
   */
  label?: string;
  
  /**
   * Label position
   * @default 'center'
   */
  labelPosition?: 'left' | 'center' | 'right';
  
  /**
   * Spacing around divider
   * @default 'md'
   */
  spacing?: 'sm' | 'md' | 'lg';
}

/**
 * Divider Component
 * 
 * Visual separator with optional label.
 * Accessible with proper ARIA role.
 * 
 * @example
 * ```tsx
 * <Divider />
 * <Divider label="OR" />
 * <Divider orientation="vertical" />
 * ```
 */
export const Divider: React.FC<DividerProps> = ({
  orientation = 'horizontal',
  label,
  labelPosition = 'center',
  spacing = 'md',
}) => {
  const spacingStyles = {
    sm: orientation === 'horizontal' ? 'my-2' : 'mx-2',
    md: orientation === 'horizontal' ? 'my-4' : 'mx-4',
    lg: orientation === 'horizontal' ? 'my-8' : 'mx-8',
  };
  
  if (orientation === 'vertical') {
    return (
      <div
        role="separator"
        aria-orientation="vertical"
        className={`w-px bg-slate-200 ${spacingStyles[spacing]}`}
      />
    );
  }
  
  if (!label) {
    return (
      <hr
        role="separator"
        className={`border-t border-slate-200 ${spacingStyles[spacing]}`}
      />
    );
  }
  
  const alignmentStyles = {
    left: 'justify-start',
    center: 'justify-center',
    right: 'justify-end',
  };
  
  return (
    <div
      role="separator"
      className={`flex items-center ${alignmentStyles[labelPosition]} ${spacingStyles[spacing]}`}
    >
      <div className="flex-1 border-t border-slate-200" />
      <span className="px-3 text-sm text-slate-500">{label}</span>
      <div className="flex-1 border-t border-slate-200" />
    </div>
  );
};
