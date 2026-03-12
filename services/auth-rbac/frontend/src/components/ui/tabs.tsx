import React from 'react';

export interface Tab {
  id: string;
  label: string;
  content: React.ReactNode;
  disabled?: boolean;
}

export interface TabsProps {
  /**
   * Array of tabs
   */
  tabs: Tab[];
  
  /**
   * Default active tab ID
   */
  defaultTab?: string;
  
  /**
   * Controlled active tab ID
   */
  activeTab?: string;
  
  /**
   * Callback when tab changes
   */
  onChange?: (tabId: string) => void;
  
  /**
   * Tabs variant
   * @default 'underline'
   */
  variant?: 'underline' | 'pills';
}

/**
 * Tabs Component
 * 
 * Accessible tabbed interface with keyboard navigation.
 * Meets WCAG 2.1 AA standards with proper ARIA attributes.
 * Supports arrow key navigation between tabs.
 * 
 * @example
 * ```tsx
 * <Tabs
 *   tabs={[
 *     { id: 'tab1', label: 'Overview', content: <div>Overview content</div> },
 *     { id: 'tab2', label: 'Details', content: <div>Details content</div> }
 *   ]}
 * />
 * ```
 */
export const Tabs: React.FC<TabsProps> = ({
  tabs,
  defaultTab,
  activeTab: controlledActiveTab,
  onChange,
  variant = 'underline',
}) => {
  const [internalActiveTab, setInternalActiveTab] = React.useState(
    defaultTab || tabs[0]?.id
  );
  
  const activeTab = controlledActiveTab ?? internalActiveTab;
  
  const handleTabClick = (tabId: string) => {
    setInternalActiveTab(tabId);
    onChange?.(tabId);
  };
  
  const handleKeyDown = (e: React.KeyboardEvent, index: number) => {
    let newIndex = index;
    
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      newIndex = index - 1 < 0 ? tabs.length - 1 : index - 1;
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      newIndex = index + 1 >= tabs.length ? 0 : index + 1;
    } else if (e.key === 'Home') {
      e.preventDefault();
      newIndex = 0;
    } else if (e.key === 'End') {
      e.preventDefault();
      newIndex = tabs.length - 1;
    }
    
    if (newIndex !== index) {
      const newTab = tabs[newIndex];
      if (!newTab.disabled) {
        handleTabClick(newTab.id);
      }
    }
  };
  
  const activeContent = tabs.find((tab) => tab.id === activeTab)?.content;
  
  const variantStyles = {
    underline: {
      container: 'border-b border-slate-200',
      tab: 'px-4 py-2 -mb-px border-b-2 border-transparent transition-colors',
      active: 'border-blue-600 text-blue-600',
      inactive: 'text-slate-600 hover:text-slate-900 hover:border-slate-300',
    },
    pills: {
      container: 'bg-slate-100 p-1 rounded-lg',
      tab: 'px-4 py-2 rounded-md transition-colors',
      active: 'bg-white text-slate-900 shadow-sm',
      inactive: 'text-slate-600 hover:text-slate-900',
    },
  };
  
  const styles = variantStyles[variant];
  
  return (
    <div>
      {/* Tab List */}
      <div className={`flex gap-2 ${styles.container}`} role="tablist">
        {tabs.map((tab, index) => {
          const isActive = tab.id === activeTab;
          
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              aria-controls={`panel-${tab.id}`}
              id={`tab-${tab.id}`}
              tabIndex={isActive ? 0 : -1}
              disabled={tab.disabled}
              onClick={() => handleTabClick(tab.id)}
              onKeyDown={(e) => handleKeyDown(e, index)}
              className={`${styles.tab} ${
                isActive ? styles.active : styles.inactive
              } disabled:opacity-50 disabled:cursor-not-allowed font-medium text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      
      {/* Tab Panels */}
      {tabs.map((tab) => (
        <div
          key={tab.id}
          role="tabpanel"
          id={`panel-${tab.id}`}
          aria-labelledby={`tab-${tab.id}`}
          hidden={tab.id !== activeTab}
          className="mt-4"
        >
          {tab.id === activeTab && tab.content}
        </div>
      ))}
    </div>
  );
};
