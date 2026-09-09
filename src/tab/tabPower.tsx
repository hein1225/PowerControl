import { FC } from "react";
import { PowerComponent } from "../components";
import { ManualLockGate } from "../components/ManualLock";

export const TabPower: FC = () => {
  return (
    <ManualLockGate>
      <PowerComponent isTab={true} />
    </ManualLockGate>
  );
};
