import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import { classSpaceStateKey } from "../../api/hooks";
import type { ClassSpaceState } from "../../api/types";
import { useAuth } from "../../store/auth";

export function useAnswerClassSpace() {
  const queryClient = useQueryClient();
  const classCode = useAuth((state) => state.me?.class_code);
  return useMutation({
    mutationFn: (showUsername: boolean) => api.put<ClassSpaceState>("/class-spaces/me/visibility", { show_username: showUsername }),
    onSuccess: (state) => {
      queryClient.setQueryData(classSpaceStateKey(classCode), state);
      void queryClient.invalidateQueries({ queryKey: ["class-space", "members"] });
      void queryClient.invalidateQueries({ queryKey: ["class-space", "messages"] });
    },
  });
}
