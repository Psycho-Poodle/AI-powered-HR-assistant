import { useEffect, useRef, useState } from "react";
import { ApiError, friendly } from "../api/client";
import { initial, parseFrame, reduce } from "./events";

export function useTaskStream(
  taskId: string | null,
  onUpdate: () => void,
  onFailure: (error: Error) => void,
) {
  const [state, setState] = useState(initial(""));
  const [connection, setConnection] = useState("idle");
  const update = useRef(onUpdate),
    failure = useRef(onFailure);
  update.current = onUpdate;
  failure.current = onFailure;
  useEffect(() => {
    if (!taskId) {
      setState(initial(""));
      setConnection("idle");
      return;
    }
    const controller = new AbortController();
    let current = initial(taskId);
    setState(current);
    async function run() {
      let delay = 500;
      while (!controller.signal.aborted) {
        try {
          setConnection(current.cursor ? "reconnecting" : "connecting");
          const response = await fetch(`/api/v1/tasks/${taskId}/events`, {
            credentials: "same-origin",
            headers: { "Last-Event-ID": String(current.cursor) },
            signal: controller.signal,
          });
          if (controller.signal.aborted) return;
          if (response.status === 204) {
            setConnection("complete");
            update.current();
            return;
          }
          if (!response.ok)
            throw new ApiError(response.status, friendly(response.status));
          if (!response.body) throw new Error("Streaming is unavailable.");
          setConnection("connected");
          delay = 500;
          const reader = response.body.getReader(),
            decoder = new TextDecoder();
          let buffer = "",
            terminal = false;
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (controller.signal.aborted) return;
              if (done) break;
              buffer = (
                buffer + decoder.decode(value, { stream: true })
              ).replace(/\r\n/g, "\n");
              let boundary;
              while ((boundary = buffer.indexOf("\n\n")) >= 0) {
                const frame = parseFrame(buffer.slice(0, boundary));
                buffer = buffer.slice(boundary + 2);
                if (!frame) continue;
                current = reduce(current, frame.event, frame.kind);
                setState(current);
                if (frame.kind === "task.terminal") {
                  terminal = true;
                  update.current();
                }
                if (
                  frame.kind === "task.updated" ||
                  frame.kind === "proposal.updated"
                )
                  update.current();
              }
            }
          } finally {
            await reader.cancel().catch(() => {});
            reader.releaseLock();
          }
          if (terminal) {
            setConnection("complete");
            return;
          }
        } catch (error) {
          if (controller.signal.aborted) return;
          if (error instanceof ApiError) {
            failure.current(error);
            setConnection("unavailable");
            return;
          }
        }
        setConnection("reconnecting");
        await new Promise<void>((resolve) => {
          const onAbort = () => {
            clearTimeout(timer);
            resolve();
          };
          const timer = setTimeout(() => {
            controller.signal.removeEventListener("abort", onAbort);
            resolve();
          }, delay);
          controller.signal.addEventListener("abort", onAbort, { once: true });
        });
        delay = Math.min(delay * 2, 10000);
      }
    }
    void run();
    return () => controller.abort();
  }, [taskId]);
  return { state, connection };
}
