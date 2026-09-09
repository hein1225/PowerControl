import {
  PanelSection,
  PanelSectionRow,
  ToggleField,
  Marquee,
  DialogButton,
  Focusable,
  quickAccessMenuClasses,
  ModalRoot,
  showModal,
  ScrollPanelGroup,
  ButtonItem,
} from "@decky/ui";
import MarkDownIt from "markdown-it";
import { useEffect, useState, FC } from "react";
import { RiArrowDownSFill, RiArrowUpSFill } from "react-icons/ri";
import {
  Settings,
  PluginManager,
  RunningApps,
  DEFAULT_APP,
  ComponentName,
  UpdateType,
  ACStateManager,
  EACState,
  Logger,
} from "../util";
import { getPowerInfo, getPowerStationStatus, setPowerStationDisabled, repairPowerstationMask } from "../util/backend";
import { AITuneConfigComponent, SettingsAITuneGateComponent } from "./aiTune";
import { localizeStrEnum, localizationManager } from "../i18n";
import { FaExclamationCircle } from "react-icons/fa";

const SettingsEnableComponent: FC = () => {
  (globalThis as any).__traceRender?.("SettingsEnableComponent");
  const [enable, setEnable] = useState<boolean>(Settings.ensureEnable());
  const refresh = () => {
    setEnable(Settings.ensureEnable());
  };
  //listen Settings
  useEffect(() => {
    if (!enable) {
      PluginManager.updateAllComponent(UpdateType.HIDE);
    } else {
      PluginManager.updateAllComponent(UpdateType.SHOW);
    }
    PluginManager.listenUpdateComponent(
      ComponentName.SET_ENABLE,
      [ComponentName.SET_ENABLE],
      (_ComponentName, updateType) => {
        switch (updateType) {
          case UpdateType.UPDATE: {
            refresh();
            break;
          }
        }
      }
    );
  }, []);
  return (
    <div>
      <PanelSectionRow>
        <ToggleField
          label={localizationManager.getString(localizeStrEnum.ENABLE_SETTINGS)}
          checked={enable}
          onChange={(enabled) => {
            Settings.setEnable(enabled);
          }}
        />
      </PanelSectionRow>
    </div>
  );
};

const SettingsPerAppComponent: FC = () => {
  const [override, setOverWrite] = useState<boolean>(Settings.appOverWrite());
  const [overrideable, setOverWriteable] = useState<boolean>(
    RunningApps.active() != DEFAULT_APP
  );
  const [show, setShow] = useState<boolean>(Settings.ensureEnable());
  const hide = (ishide: boolean) => {
    setShow(!ishide);
  };
  const refresh = () => {
    setOverWrite(Settings.appOverWrite());
    setOverWriteable(RunningApps.active() != DEFAULT_APP);
  };
  //listen Settings
  useEffect(() => {
    PluginManager.listenUpdateComponent(
      ComponentName.SET_PERAPP,
      [ComponentName.SET_PERAPP],
      (_ComponentName, updateType: string) => {
        switch (updateType) {
          case UpdateType.UPDATE:
            refresh();
            //console.log(`fn:invoke refresh:${updateType} ${UpdateType.UPDATE}`)
            break;
          case UpdateType.SHOW:
            hide(false);
            //console.log(`fn:invoke show:${updateType} ${UpdateType.SHOW}`)
            break;
          case UpdateType.HIDE:
            hide(true);
            //console.log(`fn:invoke hide:${updateType} ${UpdateType.HIDE}`)
            break;
        }
      }
    );
  }, []);

  // console.log(
  //   `######## >>>>>>>> active_appInfo:`,
  //   JSON.stringify(RunningApps.active_appInfo(), null, 2)
  // );

  return (
    <div>
      {show && (
        <PanelSectionRow>
          <ToggleField
            label={localizationManager.getString(
              localizeStrEnum.USE_PERGAME_PROFILE
            )}
            description={
              <div style={{ display: "flex", justifyContent: "left" }}>
                <img
                  src={
                    RunningApps.active_appInfo()?.icon_data
                      ? "data:image/" +
                        RunningApps.active_appInfo()?.icon_data_format +
                        ";base64," +
                        RunningApps.active_appInfo()?.icon_data
                      : "/assets/" +
                        RunningApps.active_appInfo()?.appid +
                        "/" +
                        RunningApps.active_appInfo()?.icon_hash +
                        ".jpg?c=" +
                        RunningApps.active_appInfo()?.local_cache_version
                  }
                  width={20}
                  height={20}
                  style={{
                    marginRight: "5px",
                    display: override && overrideable ? "block" : "none",
                    borderRadius: "4px",
                  }}
                />
                <div style={{ lineHeight: "20px", whiteSpace: "pre" }}>
                  {localizationManager.getString(localizeStrEnum.USING) +
                    (override && overrideable ? "『" : "")}
                </div>
                {/* @ts-ignore */}
                <Marquee
                  play={true}
                  fadeLength={10}
                  delay={1}
                  style={{
                    maxWidth: "100px",
                    lineHeight: "20px",
                    whiteSpace: "pre",
                  }}
                >
                  {override && overrideable
                    ? `${RunningApps.active_appInfo()?.display_name}`
                    : `${localizationManager.getString(
                        localizeStrEnum.DEFAULT
                      )}`}
                </Marquee>
                <div style={{ lineHeight: "20px", whiteSpace: "pre" }}>
                  {(override && overrideable ? "』" : "") +
                    localizationManager.getString(localizeStrEnum.PROFILE)}
                </div>
              </div>
            }
            checked={override && overrideable}
            disabled={!overrideable}
            onChange={(override) => {
              Settings.setOverWrite(override);
            }}
          />
        </PanelSectionRow>
      )}
    </div>
  );
};

const SettingsPerAcStateComponent: FC = () => {
  const [appACStateOverWrite, setAppACStateOverWrite] = useState<boolean>(
    Settings.appACStateOverWrite()
  );
  const [acstate, setACState] = useState<EACState>(ACStateManager.getACState());
  const [show, setShow] = useState<boolean>(Settings.ensureEnable());

  const hide = (ishide: boolean) => {
    setShow(!ishide);
  };

  const refresh = () => {
    setAppACStateOverWrite(Settings.appACStateOverWrite());
    setACState(ACStateManager.getACState());
  };

  useEffect(() => {
    PluginManager.listenUpdateComponent(
      ComponentName.SET_PERACMODE,
      [ComponentName.SET_PERACMODE],
      (_ComponentName, updateType: string) => {
        switch (updateType) {
          case UpdateType.UPDATE:
            refresh();
            break;
          case UpdateType.SHOW:
            hide(false);
            break;
          case UpdateType.HIDE:
            hide(true);
            break;
        }
      }
    );
  });

  const getAcSteteName = (acstate: EACState) => {
    if (acstate === EACState.Connected) {
      return localizationManager.getString(localizeStrEnum.AC_MODE);
    } else if (acstate === EACState.Disconnected) {
      return localizationManager.getString(localizeStrEnum.BAT_MODE);
    }
    return acstate;
  };

  const getDescription = (acstate: EACState) => {
    return (
      localizationManager.getString(localizeStrEnum.USING) +
      (appACStateOverWrite ? "『" : "") +
      (appACStateOverWrite
        ? getAcSteteName(acstate)
        : localizationManager.getString(localizeStrEnum.DEFAULT)) +
      (appACStateOverWrite ? "』" : "") +
      localizationManager.getString(localizeStrEnum.PROFILE)
    );
  };

  return (
    <div>
      {show && (
        <PanelSectionRow>
          <ToggleField
            label={localizationManager.getString(
              localizeStrEnum.USE_PERACMODE_PROFILE
            )}
            description={getDescription(acstate)}
            checked={appACStateOverWrite}
            onChange={(override) => {
              Settings.setACStateOverWrite(override);
            }}
          />
        </PanelSectionRow>
      )}
    </div>
  );
};

const SettingsPollingComponent: FC = () => {
  const [enabled, setEnabled] = useState<boolean>(Settings.appPollingEnabled());
  const [show, setShow] = useState<boolean>(Settings.ensureEnable());

  useEffect(() => {
    PluginManager.listenUpdateComponent(
      ComponentName.SETTINGS_POLLING,
      [ComponentName.SETTINGS_POLLING],
      (_ComponentName, updateType: string) => {
        if (updateType === UpdateType.UPDATE) {
          setEnabled(Settings.appPollingEnabled());
          setShow(Settings.ensureEnable());
        } else if (updateType === UpdateType.SHOW) {
          setShow(true);
        } else if (updateType === UpdateType.HIDE) {
          setShow(false);
        }
      }
    );
  }, []);

  if (!show) return null;

  return (
    <PanelSectionRow>
      <ToggleField
        label={localizationManager.getString(localizeStrEnum.SETTINGS_POLLING)}
        description={localizationManager.getString(
          localizeStrEnum.SETTINGS_POLLING_DESC
        )}
        checked={enabled}
        onChange={(value) => {
          Settings.setPollingEnabled(value);
        }}
      />
    </PanelSectionRow>
  );
};

export const SettingsComponent: FC<{
  isTab?: boolean;
}> = ({ isTab = false }) => {
  const [showSettings, setShowSettings] = useState<boolean>(
    Settings.showSettingMenu
  );
  const updateShowSettings = (show: boolean) => {
    setShowSettings(show);
    Settings.showSettingMenu = show;
  };

  // PowerStation 开关（Bazzite 44+ TDP 防重置）
  const [psStatus, setPsStatus] = useState<any>(null);
  const [psDisabled, setPsDisabled] = useState<boolean>(false);
  const [psBusy, setPsBusy] = useState<boolean>(false);
  const [psRepairing, setPsRepairing] = useState<boolean>(false);
  const [psRepairMsg, setPsRepairMsg] = useState<string>("");
  const [psNotInstalled, setPsNotInstalled] = useState<boolean>(false);
  useEffect(() => {
    getPowerStationStatus()
      .then((s: any) => {
        setPsStatus(s);
        setPsDisabled(!!s?.disabled_by_plugin);
        setPsNotInstalled(!!s && s.exists === false);
      })
      .catch(() => {});
  }, []);
  const onTogglePowerStation = async (v: boolean) => {
    setPsBusy(true);
    try {
      const ok = await setPowerStationDisabled(v);
      if (ok) {
        setPsDisabled(v);
        const s = await getPowerStationStatus();
        setPsStatus(s);
      }
    } catch (e) {
      console.error("setPowerStationDisabled failed", e);
    } finally {
      setPsBusy(false);
    }
  };
  // 按需修复：移除历史版本误留的 powerstation mask 软链（导致系统卡死的持久副作用）。
  // 仅在用户点击时触发，绝不在插件加载期自动运行（避免加载期卡死）。
  const onRepairPowerStation = async () => {
    setPsRepairing(true);
    setPsRepairMsg("修复中…");
    try {
      const r = await repairPowerstationMask();
      if (r?.error) {
        setPsRepairMsg("修复失败：" + r.error);
      } else if (r?.unmasked) {
        setPsRepairMsg("已解除屏蔽，系统恢复正常 ✓");
      } else {
        setPsRepairMsg("未发现屏蔽，无需修复 ✓");
      }
      const s = await getPowerStationStatus();
      setPsStatus(s);
    } catch (e: any) {
      setPsRepairMsg("修复异常：" + String(e));
    } finally {
      setPsRepairing(false);
    }
  };

  return (
    <>
      <PanelSection
        title={localizationManager.getString(localizeStrEnum.TITEL_SETTINGS)}
      >
        {!isTab && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              // @ts-ignore
              style={{
                height: "20px",
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
              }}
              onClick={() => updateShowSettings(!showSettings)}
            >
              {showSettings ? <RiArrowUpSFill /> : <RiArrowDownSFill />}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {(showSettings || isTab) && (
          <>
            <SettingsEnableComponent />
            <SettingsPerAppComponent />
            <SettingsPerAcStateComponent />
            <SettingsPollingComponent />
            <AITuneConfigComponent />
            <SettingsAITuneGateComponent />
            <PanelSection title="系统兼容 (Bazzite 44+)">
              <PanelSectionRow>
                <ToggleField
                  label="禁用 PowerStation（防止 TDP 被重置）"
                  description="Bazzite 44 把 TDP 控制权交给了 SteamOS-Manager/PowerStation，它会在进游戏时覆盖 PowerContorlAI 的 TDP。关闭后由 PowerContorlAI 完全接管（含风扇）。需 root 权限。"
                  checked={psDisabled}
                  disabled={psNotInstalled || psBusy}
                  onChange={onTogglePowerStation}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  disabled={psRepairing || psNotInstalled}
                  onClick={onRepairPowerStation}
                >
                  {psRepairing ? "修复中…" : "修复系统 powerstation 状态（解除卡死）"}
                </ButtonItem>
              </PanelSectionRow>
              {psStatus && (
                <PanelSectionRow>
                  <div style={{ fontSize: 12, opacity: 0.7, lineHeight: 1.5 }}>
                    状态：
                    {!psStatus.exists
                      ? "未安装 powerstation（无需处理）"
                      : psStatus.active
                      ? "运行中（正在接管 TDP）"
                      : psStatus.masked
                      ? "已屏蔽（不接管 TDP）"
                      : psStatus.enabled
                      ? "已启用（会接管 TDP）"
                      : "存在但未启用"}
                    {" · "}
                    {psDisabled ? "已设为禁用（开机自动保持）" : "未禁用"}
                    {psBusy ? " · 操作中…" : ""}
                  </div>
                </PanelSectionRow>
              )}
              {psRepairMsg && (
                <PanelSectionRow>
                  <div style={{ fontSize: 12, opacity: 0.85 }}>{psRepairMsg}</div>
                </PanelSectionRow>
              )}
            </PanelSection>
          </>
        )}
      </PanelSection>
    </>
  );
};

const buttonStyle = {
  height: "28px",
  width: "40px",
  minWidth: 0,
  padding: 0,
  display: "flex",
  justifyContent: "center",
  alignItems: "center",
};

export const QuickAccessTitleView: FC<{ title: string }> = ({ title }) => {
  return (
    // @ts-ignore
    <Focusable
      style={{
        display: "flex",
        padding: "0",
        flex: "auto",
        boxShadow: "none",
      }}
      className={quickAccessMenuClasses.Title}
    >
      <div style={{ marginRight: "auto" }}>{title}</div>
      <DialogButton
        onOKActionDescription="Power Info"
        style={buttonStyle}
        onClick={() => {
          showModal(<PowerInfoModel />);
        }}
      >
        <FaExclamationCircle size="0.9em" />
      </DialogButton>
    </Focusable>
  );
};

export const PowerInfoModel: FC = ({
  closeModal,
}: {
  closeModal?: () => void;
}) => {
  const fontStyle: React.CSSProperties = {
    fontFamily:
      "'DejaVu Sans Mono', Hack, 'Source Code Pro', 'Courier New', monospace, Consolas",
    fontSize: "12px",
    lineHeight: "0.2", // 调整行距
    maxHeight: "300px", // 设置最大高度
    overflow: "auto", // 添加滚动条
    whiteSpace: "pre",
    margin: "10px 0",
  };

  // @ts-ignore
  const mdIt = new MarkDownIt({
    html: true,
  });

  const [info, setInfo] = useState<string>("");
  Logger.info(`fn:invoke PowerInfoModel: ${info}`);

  const fetchPowerInfo = () => {
    // if amd
    // if (Backend.data.getCpuVendor() === "AuthenticAMD") {
    //   Logger.info(`fn:invoke getRyzenadjInfo`);
    //   Backend.getRyzenadjInfo().then((info) => {
    //     setInfo(info);
    //   });
    // } else {
    //   Logger.info(`fn:invoke getRAPLInfo`);
    //   Backend.getRAPLInfo().then((info) => {
    //     setInfo(info);
    //   });
    // }
    Logger.info(`fn:invoke getPowerInfo`);
    getPowerInfo().then((info: string) => {
      setInfo(info);
    });
  };

  useEffect(() => {
    fetchPowerInfo();

    // 每5秒刷新一次
    const interval = setInterval(() => {
      fetchPowerInfo();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <ModalRoot closeModal={closeModal}>
      <div>
        <PanelSection title={"Power Info"}>
          <PanelSectionRow>
            <DialogButton
              onClick={() => {
                fetchPowerInfo();
              }}
            >
              Reload
            </DialogButton>
          </PanelSectionRow>
          <ScrollPanelGroup
            //@ts-ignore
            focusable={false}
          >
            <Focusable
              children={
                <div style={fontStyle}>
                  {info.split("\n").map((line, index) => (
                    <p key={index}>{line}</p>
                  ))}
                </div>
              }
            ></Focusable>
          </ScrollPanelGroup>
        </PanelSection>
      </div>
    </ModalRoot>
  );
};
