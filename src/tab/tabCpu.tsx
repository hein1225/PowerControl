import { FC } from "react";
import { CPUComponent } from "../components";
import { ManualLockGate } from "../components/ManualLock";

export const TabCpu: FC = () => {
  return (
    <ManualLockGate>
      <CPUComponent isTab={true} />
    </ManualLockGate>
  );
};
