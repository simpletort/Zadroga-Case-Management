import React, { useState } from "react";
import { useNavigate, Link } from "react-router";
import { CheckCircle, Mail, Lock, User, AlertCircle } from "lucide-react";
import { useAuth } from "../lib/AuthContext";
import { signInWithEmailAndPassword } from "firebase/auth";
import { auth } from "../lib/firebase";
import { registerUser, createSession } from "../lib/api";

export function Signup() {
  const navigate = useNavigate();
  const [formData, setFormData] = useState({ name: "", email: "", password: "", confirmPassword: "", portalToken: "" });
  const [error,   setError]   = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  // Read invite token from URL if present (?token=xxx&email=xxx)
  const params = new URLSearchParams(window.location.search);
  const tokenFromUrl = params.get("token") ?? "";
  const emailFromUrl = params.get("email") ?? "";

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) =>
    setFormData({ ...formData, [e.target.name]: e.target.value });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!formData.name || !formData.email || !formData.password || !formData.confirmPassword) {
      setError("Please fill in all fields"); return;
    }
    if (formData.password !== formData.confirmPassword) {
      setError("Passwords do not match"); return;
    }
    setLoading(true);
    try {
      await registerUser({
        email:        formData.email,
        password:     formData.password,
        display_name: formData.name,
        portal_token: tokenFromUrl || formData.portalToken || undefined,
      });
      setSuccess(true);
      // Auto sign-in after registration
      const cred = await signInWithEmailAndPassword(auth, formData.email, formData.password);
      const idToken = await cred.user.getIdToken();
      await createSession(idToken);
      setTimeout(() => navigate("/"), 1500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-slate-900 mb-2">Create Account</h1>
          <p className="text-slate-600">Join the Case Management Portal</p>
        </div>
        <div className="bg-white border border-slate-200 rounded-2xl shadow-lg p-8">
          {success ? (
            <div className="text-center py-8">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full mb-4">
                <CheckCircle className="w-10 h-10 text-green-600" />
              </div>
              <h2 className="text-xl font-semibold text-slate-900 mb-2">Account Created!</h2>
              <p className="text-sm text-slate-600">Redirecting you to the dashboard…</p>
              <div className="flex justify-center mt-4">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
              </div>
            </div>
          ) : (
            <>
              <h2 className="text-xl font-semibold text-slate-900 mb-6 text-center">Get started</h2>
              <form onSubmit={handleSubmit} className="space-y-4">
                {error && (
                  <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" /><span>{error}</span>
                  </div>
                )}
                {[
                  { label: "Full Name", name: "name", type: "text", icon: User, placeholder: "John Doe", value: formData.name },
                  { label: "Email Address", name: "email", type: "email", icon: Mail, placeholder: "you@simpletort.com", value: emailFromUrl || formData.email },
                  { label: "Password", name: "password", type: "password", icon: Lock, placeholder: "Min 8 chars, 1 upper, 1 special", value: formData.password },
                  { label: "Confirm Password", name: "confirmPassword", type: "password", icon: Lock, placeholder: "Re-enter your password", value: formData.confirmPassword },
                ].map(({ label, name, type, icon: Icon, placeholder, value }) => (
                  <div key={name}>
                    <label className="block text-sm font-medium text-slate-700 mb-2">{label}</label>
                    <div className="relative">
                      <Icon className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                      <input name={name} type={type} value={value} onChange={handleChange} placeholder={placeholder} required disabled={loading}
                        className="w-full pl-10 pr-4 py-2.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50" />
                    </div>
                  </div>
                ))}
                <button type="submit" disabled={loading}
                  className="w-full py-2.5 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2">
                  {loading ? <><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" /> Creating account…</> : "Create Account"}
                </button>
              </form>
            </>
          )}
        </div>
        {!success && (
          <div className="mt-6 text-center text-sm text-slate-600">
            Already have an account?{" "}
            <Link to="/login" className="text-blue-600 hover:underline font-medium">Sign in</Link>
          </div>
        )}
      </div>
    </div>
  );
}
