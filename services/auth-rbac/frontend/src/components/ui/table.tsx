import React from 'react';

export interface TableProps extends React.TableHTMLAttributes<HTMLTableElement> {
  /**
   * Striped rows
   * @default false
   */
  striped?: boolean;
  
  /**
   * Hoverable rows
   * @default false
   */
  hoverable?: boolean;
  
  /**
   * Bordered table
   * @default false
   */
  bordered?: boolean;
}

/**
 * Table Component
 * 
 * Accessible data table with proper semantic markup.
 * Meets WCAG 2.1 AA standards with proper headers and structure.
 * 
 * @example
 * ```tsx
 * <Table striped hoverable>
 *   <TableHead>
 *     <TableRow>
 *       <TableHeader>Name</TableHeader>
 *       <TableHeader>Email</TableHeader>
 *     </TableRow>
 *   </TableHead>
 *   <TableBody>
 *     <TableRow>
 *       <TableCell>John Doe</TableCell>
 *       <TableCell>john@example.com</TableCell>
 *     </TableRow>
 *   </TableBody>
 * </Table>
 * ```
 */
export const Table: React.FC<TableProps> = ({
  striped = false,
  hoverable = false,
  bordered = false,
  className = '',
  children,
  ...props
}) => {
  const baseStyles = 'w-full text-left';
  const borderedStyles = bordered ? 'border border-slate-200' : '';
  
  return (
    <div className="overflow-x-auto">
      <table
        className={`${baseStyles} ${borderedStyles} ${className}`}
        {...props}
      >
        {children}
      </table>
    </div>
  );
};

/**
 * TableHead Component
 */
export const TableHead: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = ({
  className = '',
  children,
  ...props
}) => {
  return (
    <thead className={`bg-slate-50 border-b border-slate-200 ${className}`} {...props}>
      {children}
    </thead>
  );
};

/**
 * TableBody Component
 */
export const TableBody: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = ({
  className = '',
  children,
  ...props
}) => {
  return (
    <tbody className={className} {...props}>
      {children}
    </tbody>
  );
};

/**
 * TableRow Component
 */
export const TableRow: React.FC<React.HTMLAttributes<HTMLTableRowElement>> = ({
  className = '',
  children,
  ...props
}) => {
  return (
    <tr
      className={`border-b border-slate-200 last:border-b-0 hover:bg-slate-50 transition-colors ${className}`}
      {...props}
    >
      {children}
    </tr>
  );
};

/**
 * TableHeader Component
 */
export const TableHeader: React.FC<React.ThHTMLAttributes<HTMLTableHeaderCellElement>> = ({
  className = '',
  children,
  ...props
}) => {
  return (
    <th
      className={`px-4 py-3 text-sm font-semibold text-slate-700 ${className}`}
      {...props}
    >
      {children}
    </th>
  );
};

/**
 * TableCell Component
 */
export const TableCell: React.FC<React.TdHTMLAttributes<HTMLTableDataCellElement>> = ({
  className = '',
  children,
  ...props
}) => {
  return (
    <td
      className={`px-4 py-3 text-sm text-slate-600 ${className}`}
      {...props}
    >
      {children}
    </td>
  );
};
