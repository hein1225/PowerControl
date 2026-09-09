import { FC } from "react";
import { GPUComponent } from "../components";
import { ManualLockGate } from "../components/ManualLock";

export const TabGpu: FC = () => {
  return (
    <ManualLockGate>
      <GPUComponent isTab={true} />
    </ManualLockGate>
  );
};
