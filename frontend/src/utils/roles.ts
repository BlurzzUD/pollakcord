export function isStaffRole(role: string | null | undefined): boolean {
  return role === "school_moderator" || role === "school_admin";
}

export function canCreateForms(role: string | null | undefined): boolean {
  return role === "school_admin" || role === "school_moderator" || role === "dok_president";
}
