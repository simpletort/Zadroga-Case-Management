import React from 'react';

export interface DropdownItem {
  id: string;
  label: string;
  icon?: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  divider?: boolean;
}

export interface DropdownProps {
  /**
   * Dropdown trigger element
   */
  trigger: React.ReactElement;
  
  /**
   * Dropdown menu items
   */
  items: DropdownItem[];
  
  /**
   * Dropdown position
   * @default 'bottom-left'
   */
  position?: 'bottom-left' | 'bottom-right' | 'top-left' | 'top-right';
  
  /**
   * Close on item click
   * @default true
   */
  closeOnClick?: boolean;
}

/**
 * Dropdown Component
 * 
 * Accessible dropdown menu with keyboard navigation.
 * Meets WCAG 2.1 AA standards with proper ARIA attributes.
 * 
 * @example
 * ```tsx
 * <Dropdown
 *   trigger={<button>Menu</button>}
 *   items={[
 *     { id: '1', label: 'Edit', onClick: () => {} },
 *     { id: '2', label: 'Delete', onClick: () => {} }
 *   ]}
 * />
 * ```
 */
export const Dropdown: React.FC<DropdownProps> = ({
  trigger,
  items,
  position = 'bottom-left',
  closeOnClick = true,
}) => {
  const [isOpen, setIsOpen] = React.useState(false);
  const dropdownRef = React.useRef<HTMLDivElement>(null);
  
  React.useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };
    
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleEscape);
    }
    
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isOpen]);
  
  const positionStyles = {
    'bottom-left': 'top-full left-0 mt-2',
    'bottom-right': 'top-full right-0 mt-2',
    'top-left': 'bottom-full left-0 mb-2',
    'top-right': 'bottom-full right-0 mb-2',
  };
  
  const handleItemClick = (item: DropdownItem) => {
    if (item.disabled) return;
    
    item.onClick?.();
    
    if (closeOnClick) {
      setIsOpen(false);
    }
  };
  
  return (
    <div ref={dropdownRef} className="relative inline-block">
      {React.cloneElement(trigger, {
        onClick: () => setIsOpen(!isOpen),
        'aria-haspopup': 'true',
        'aria-expanded': isOpen,
      })}
      
      {isOpen && (
        <div
          role="menu"
          className={`absolute ${positionStyles[position]} z-50 min-w-[200px] bg-white border border-slate-200 rounded-lg shadow-lg py-1`}
        >
          {items.map((item) => (
            <React.Fragment key={item.id}>
              {item.divider ? (
                <div className="my-1 border-t border-slate-200" role="separator" />
              ) : (
                <button
                  role="menuitem"
                  onClick={() => handleItemClick(item)}
                  disabled={item.disabled}
                  className="w-full flex items-center gap-3 px-4 py-2 text-sm text-left text-slate-700 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:bg-slate-100"
                >
                  {item.icon && (
                    <span className="flex-shrink-0" aria-hidden="true">
                      {item.icon}
                    </span>
                  )}
                  <span>{item.label}</span>
                </button>
              )}
            </React.Fragment>
          ))}
        </div>
      )}
    </div>
  );
};
