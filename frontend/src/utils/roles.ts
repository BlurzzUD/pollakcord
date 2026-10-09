export function isStaffRole(role: string | null | undefined): boolean {
  return role === "school_moderator" || role === "school_admin";
}
