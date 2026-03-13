import React, { useState } from "react";
import { Link } from "react-router";
import { Mail, AlertCircle, CheckCircle, ArrowLeft } from "lucide-react";
import { requestPasswordReset } from "../lib/api";

export function ForgotPassword() {
  const [email,   setEmail]   = useState("");
  const [error,   setError]   = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!email) { setError("Please enter your email address"); return; }
    setLoading(true);
    try {
      await requestPasswordReset(email);
      setSuccess(true);
    } catch {
      // Always show success to prevent email enumeration
      setSuccess(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-slate-900 mb-2">Reset Password</h1>
          <p className="text-slate-600">{success ? "Check your email" : "Enter your email to receive reset instructions"}</p>
        </div>
        <div className="bg-white border border-slate-200 rounded-2xl shadow-lg p-8">
          {success ? (
            <div className="text-center py-4">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full mb-4">
                <CheckCircle className="w-10 h-10 text-green-600" />
              </div>
              <h2 className="text-xl font-semibold text-slate-900 mb-2">Email Sent!</h2>
              <p className="text-sm text-slate-600 mb-2">If this email is registered, a reset link has been sent to:</p>
              <p className="text-sm font-medium text-slate-900 mb-6">{email}</p>
              <Link to="/login" className="inline-flex items-center gap-2 text-blue-600 hover:underline text-sm font-medium">
                <ArrowLeft className="w-4 h-4" /> Back to login
              </Link>
            </div>
          ) : (
            <>
              <h2 className="text-xl font-semibold text-slate-900 mb-6 text-center">Forgot your password?</h2>
              <form onSubmit={handleSubmit} className="space-y-4">
                {error && (
                  <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" /><span>{error}</span>
                  </div>
                )}
                <div>
                  <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-2">Email Address</label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                    <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@simpletort.com" disabled={loading}
                      className="w-full pl-10 pr-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50" />
                  </div>
                </div>
                <button type="submit" disabled={loading}
                  className="w-full py-2.5 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2">
                  {loading ? <><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" /> Sending…</> : "Send Reset Link"}
                </button>
              </form>
              <div className="mt-6 text-center">
                <Link to="/login" className="inline-flex items-center gap-2 text-slate-600 hover:text-slate-900 text-sm font-medium">
                  <ArrowLeft className="w-4 h-4" /> Back to login
                </Link>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
