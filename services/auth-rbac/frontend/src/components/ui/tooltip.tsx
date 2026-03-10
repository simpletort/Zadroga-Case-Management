import React from 'react';

export interface TooltipProps {
  /**
   * Content to display in tooltip
   */
  content: React.ReactNode;
  
  /**
   * Tooltip position
   * @default 'top'
   */
  position?: 'top' | 'bottom' | 'left' | 'right';
  
  /**
   * Element that triggers the tooltip
   */
  children: React.ReactElement;
  
  /**
   * Delay before showing tooltip (ms)
   * @default 200
   */
  delay?: number;
}

/**
 * Tooltip Component
 * 
 * Accessible tooltip that appears on hover/focus.
 * Meets WCAG 2.1 AA standards with keyboard accessibility.
 * 
 * @example
 * ```tsx
 * <Tooltip content="Click to edit">
 *   <button>Edit</button>
 * </Tooltip>
 * <Tooltip content="User information" position="right">
 *   <InfoIcon />
 * </Tooltip>
 * ```
 */
export const Tooltip: React.FC<TooltipProps> = ({
  content,
  position = 'top',
  children,
  delay = 200,
}) => {
  const [isVisible, setIsVisible] = React.useState(false);
  const timeoutRef = React.useRef<NodeJS.Timeout>();
  
  const showTooltip = () => {
    timeoutRef.current = setTimeout(() => {
      setIsVisible(true);
    }, delay);
  };
  
  const hideTooltip = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    setIsVisible(false);
  };
  
  React.useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);
  
  const positionStyles = {
    top: 'bottom-full left-1/2 -translate-x-1/2 -translate-y-2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 translate-y-2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 -translate-x-2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 translate-x-2 ml-2',
  };
  
  const arrowPositionStyles = {
    top: 'top-full left-1/2 -translate-x-1/2 border-l-transparent border-r-transparent border-b-transparent border-t-slate-900',
    bottom: 'bottom-full left-1/2 -translate-x-1/2 border-l-transparent border-r-transparent border-t-transparent border-b-slate-900',
    left: 'left-full top-1/2 -translate-y-1/2 border-t-transparent border-b-transparent border-r-transparent border-l-slate-900',
    right: 'right-full top-1/2 -translate-y-1/2 border-t-transparent border-b-transparent border-l-transparent border-r-slate-900',
  };
  
  return (
    <div
      className="relative inline-block"
      onMouseEnter={showTooltip}
      onMouseLeave={hideTooltip}
      onFocus={showTooltip}
      onBlur={hideTooltip}
    >
      {children}
      
      {isVisible && (
        <div
          role="tooltip"
          className={`absolute ${positionStyles[position]} z-50 px-2 py-1 text-xs text-white bg-slate-900 rounded shadow-lg whitespace-nowrap pointer-events-none`}
        >
          {content}
          <div
            className={`absolute ${arrowPositionStyles[position]} border-4`}
            aria-hidden="true"
          />
        </div>
      )}
    </div>
  );
};
