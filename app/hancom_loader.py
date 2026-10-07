from __future__ import annotations

from pathlib import Path
import tempfile


class HancomAutomationError(RuntimeError):
    pass


def convert_hwp_to_hwpx(path: str | Path) -> Path:
    """Windows의 설치된 한/글을 이용해 HWP를 임시 HWPX로 변환한다.

    문서는 외부 서버로 전송하지 않는다. 변환 파일은 임시 폴더에만 생성된다.
    호출자가 반환된 파일과 부모 임시 폴더를 정리해야 한다.
    """
    source = Path(path).resolve()

    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise HancomAutomationError(
            "HWP 문서를 열려면 Windows용 한/글과 pywin32 구성 요소가 필요합니다."
        ) from exc

    pythoncom.CoInitialize()
    hwp = None
    temp_dir = Path(tempfile.mkdtemp(prefix="public_language_hwp_"))
    output = temp_dir / f"{source.stem}.hwpx"

    try:
        try:
            hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
        except Exception as exc:
            raise HancomAutomationError(
                "설치된 한/글 프로그램을 찾지 못했습니다. "
                "HWP 파일은 한/글이 설치된 Windows PC에서만 직접 열 수 있습니다."
            ) from exc

        # 창은 숨기되, 환경에 따라 파일 접근 승인 창이 나타날 수 있다.
        try:
            hwp.XHwpWindows.Item(0).Visible = False
        except Exception:
            pass

        try:
            opened = hwp.Open(str(source), "HWP", "forceopen:true")
        except Exception:
            opened = hwp.Open(str(source), "", "")

        if not opened:
            raise HancomAutomationError(
                "한/글이 HWP 문서를 열지 못했습니다. 암호·배포용 문서 여부를 확인해 주세요."
            )

        saved = False
        try:
            saved = bool(hwp.SaveAs(str(output), "HWPX", ""))
        except Exception:
            saved = False

        if not saved:
            try:
                hwp.HAction.GetDefault(
                    "FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet
                )
                hwp.HParameterSet.HFileOpenSave.FileName = str(output)
                hwp.HParameterSet.HFileOpenSave.Format = "HWPX"
                hwp.HParameterSet.HFileOpenSave.Attributes = 0
                saved = bool(
                    hwp.HAction.Execute(
                        "FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet
                    )
                )
            except Exception as exc:
                raise HancomAutomationError(
                    "HWP를 HWPX로 변환하지 못했습니다."
                ) from exc

        if not output.exists() or output.stat().st_size == 0:
            raise HancomAutomationError(
                "HWPX 임시 변환 파일이 생성되지 않았습니다."
            )

        return output

    finally:
        if hwp is not None:
            try:
                hwp.Clear(1)
            except Exception:
                pass
            try:
                hwp.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()
