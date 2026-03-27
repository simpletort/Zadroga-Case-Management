import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, PieChart, Pie, Legend } from 'recharts';
import { Users, Clock, CheckCircle } from 'lucide-react';
import { mockCases } from '../mock-data';

export function WorkloadDistribution() {
  // Analyze workload by paralegal
  const workloadByParalegal = mockCases.reduce((acc, caseItem) => {
    if (!acc[caseItem.assignedTo]) {
      acc[caseItem.assignedTo] = {
        name: caseItem.assignedTo,
        total: 0,
        active: 0,
        pending: 0,
        underReview: 0,
        submitted: 0
      };
    }
    acc[caseItem.assignedTo].total++;
    
    if (caseItem.status === 'Active') acc[caseItem.assignedTo].active++;
    else if (caseItem.status === 'Pending Review') acc[caseItem.assignedTo].pending++;
    else if (caseItem.status === 'Under Review') acc[caseItem.assignedTo].underReview++;
    else if (caseItem.status === 'Submitted') acc[caseItem.assignedTo].submitted++;
    
    return acc;
  }, {} as Record<string, any>);

  const workloadData = Object.values(workloadByParalegal);

  // Case status distribution
  const statusDistribution = mockCases.reduce((acc, caseItem) => {
    acc[caseItem.status] = (acc[caseItem.status] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  const statusData = Object.entries(statusDistribution).map(([status, count]) => ({
    name: status,
    value: count
  }));

  const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444'];

  // Case type distribution
  const wtcCount = mockCases.filter(c => c.caseType === 'WTC').length;
  const vcfCount = mockCases.filter(c => c.caseType === 'VCF').length;

  // Average metrics
  const avgMedicalScore = Math.round(mockCases.reduce((sum, c) => sum + c.medicalScore, 0) / mockCases.length);
  const avgConfidence = Math.round(mockCases.reduce((sum, c) => sum + c.medicalConfidence, 0) / mockCases.length);

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600">Total Cases</p>
              <p className="text-2xl font-bold text-slate-900">{mockCases.length}</p>
            </div>
            <Users className="w-8 h-8 text-blue-600" />
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600">Active Cases</p>
              <p className="text-2xl font-bold text-green-600">
                {mockCases.filter(c => c.status === 'Active').length}
              </p>
            </div>
            <Clock className="w-8 h-8 text-green-600" />
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600">Avg Medical Score</p>
              <p className="text-2xl font-bold text-purple-600">{avgMedicalScore}%</p>
            </div>
            <CheckCircle className="w-8 h-8 text-purple-600" />
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600">Avg AI Confidence</p>
              <p className="text-2xl font-bold text-blue-600">{avgConfidence}%</p>
            </div>
            <CheckCircle className="w-8 h-8 text-blue-600" />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Workload by Paralegal */}
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <h3 className="text-lg font-medium text-slate-900 mb-4">Workload by Paralegal</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={workloadData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="active" stackId="a" fill="#10b981" name="Active" />
              <Bar dataKey="pending" stackId="a" fill="#f59e0b" name="Pending Review" />
              <Bar dataKey="underReview" stackId="a" fill="#3b82f6" name="Under Review" />
              <Bar dataKey="submitted" stackId="a" fill="#8b5cf6" name="Submitted" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Case Status Distribution */}
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <h3 className="text-lg font-medium text-slate-900 mb-4">Case Status Distribution</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={statusData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                outerRadius={80}
                fill="#8884d8"
                dataKey="value"
              >
                {statusData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Case Type Breakdown */}
      <div className="bg-white border border-slate-200 rounded-lg p-4">
        <h3 className="text-lg font-medium text-slate-900 mb-4">Case Type Distribution</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <p className="text-sm text-blue-700 mb-1">WTC Cases</p>
            <p className="text-3xl font-bold text-blue-900">{wtcCount}</p>
            <p className="text-xs text-blue-600 mt-1">
              {((wtcCount / mockCases.length) * 100).toFixed(1)}% of total
            </p>
          </div>
          <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
            <p className="text-sm text-purple-700 mb-1">VCF Cases</p>
            <p className="text-3xl font-bold text-purple-900">{vcfCount}</p>
            <p className="text-xs text-purple-600 mt-1">
              {((vcfCount / mockCases.length) * 100).toFixed(1)}% of total
            </p>
          </div>
        </div>
      </div>

      {/* Detailed Paralegal Stats */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="px-4 py-3 bg-slate-50 border-b border-slate-200">
          <h3 className="text-lg font-medium text-slate-900">Paralegal Performance</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-700 uppercase tracking-wider">
                  Paralegal
                </th>
                <th className="px-4 py-3 text-center text-xs font-medium text-slate-700 uppercase tracking-wider">
                  Total Cases
                </th>
                <th className="px-4 py-3 text-center text-xs font-medium text-slate-700 uppercase tracking-wider">
                  Active
                </th>
                <th className="px-4 py-3 text-center text-xs font-medium text-slate-700 uppercase tracking-wider">
                  Pending Review
                </th>
                <th className="px-4 py-3 text-center text-xs font-medium text-slate-700 uppercase tracking-wider">
                  Under Review
                </th>
                <th className="px-4 py-3 text-center text-xs font-medium text-slate-700 uppercase tracking-wider">
                  Submitted
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {workloadData.map((paralegal) => (
                <tr key={paralegal.name} className="hover:bg-slate-50">
                  <td className="px-4 py-3 text-sm font-medium text-slate-900">
                    {paralegal.name}
                  </td>
                  <td className="px-4 py-3 text-sm text-center text-slate-700">
                    {paralegal.total}
                  </td>
                  <td className="px-4 py-3 text-sm text-center">
                    <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full">
                      {paralegal.active}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-center">
                    <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded-full">
                      {paralegal.pending}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-center">
                    <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full">
                      {paralegal.underReview}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-center">
                    <span className="px-2 py-1 bg-purple-100 text-purple-800 rounded-full">
                      {paralegal.submitted}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
