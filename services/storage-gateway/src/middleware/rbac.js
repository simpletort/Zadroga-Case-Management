/**
 * RBAC middleware — checks that the authenticated user has one of the required roles.
 * Expects req.user to be populated by upstream auth middleware (e.g. JWT verification).
 *
 * Usage: requireRole(['admin', 'attorney'])
 */
function requireRole(allowedRoles) {
  return (req, res, next) => {
    const user = req.user;

    if (!user) {
      return res.status(401).json({ error: 'Unauthorized: no authenticated user.' });
    }

    if (!allowedRoles.includes(user.role)) {
      return res.status(403).json({
        error: `Forbidden: role "${user.role}" is not permitted to perform this action.`,
      });
    }

    next();
  };
}

module.exports = { requireRole };