#include "flutter_window.h"

#include <optional>
#include <wincred.h>
#include <flutter/standard_method_codec.h>

#include "flutter/generated_plugin_registrant.h"

FlutterWindow::FlutterWindow(const flutter::DartProject& project)
    : project_(project) {}

FlutterWindow::~FlutterWindow() {}

bool FlutterWindow::OnCreate() {
  if (!Win32Window::OnCreate()) {
    return false;
  }

  RECT frame = GetClientArea();

  // The size here must match the window dimensions to avoid unnecessary surface
  // creation / destruction in the startup path.
  flutter_controller_ = std::make_unique<flutter::FlutterViewController>(
      frame.right - frame.left, frame.bottom - frame.top, project_);
  // Ensure that basic setup of the controller was successful.
  if (!flutter_controller_->engine() || !flutter_controller_->view()) {
    return false;
  }
  RegisterPlugins(flutter_controller_->engine());
  secure_channel_ = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      flutter_controller_->engine()->messenger(), "cn.shijuan/secure",
      &flutter::StandardMethodCodec::GetInstance());
  secure_channel_->SetMethodCallHandler(
      [](const flutter::MethodCall<flutter::EncodableValue>& call,
         std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
        const wchar_t* target = L"cn.shijuan.studio.service-token";
        if (call.method_name() == "read") {
          PCREDENTIALW credential = nullptr;
          if (CredReadW(target, CRED_TYPE_GENERIC, 0, &credential)) {
            std::string value(reinterpret_cast<char*>(credential->CredentialBlob),
                              credential->CredentialBlobSize);
            CredFree(credential);
            result->Success(flutter::EncodableValue(value));
          } else if (GetLastError() == ERROR_NOT_FOUND) {
            result->Success(flutter::EncodableValue(""));
          } else {
            result->Error("storage", "Unable to read service credential.");
          }
        } else if (call.method_name() == "write") {
          const auto* value = call.arguments() ? std::get_if<std::string>(call.arguments()) : nullptr;
          if (!value || value->size() > CRED_MAX_CREDENTIAL_BLOB_SIZE) {
            result->Error("storage", "Invalid service credential.");
            return;
          }
          if (value->empty()) {
            if (!CredDeleteW(target, CRED_TYPE_GENERIC, 0) && GetLastError() != ERROR_NOT_FOUND) {
              result->Error("storage", "Unable to remove service credential.");
              return;
            }
          } else {
            CREDENTIALW credential{};
            credential.Type = CRED_TYPE_GENERIC;
            credential.TargetName = const_cast<LPWSTR>(target);
            credential.CredentialBlobSize = static_cast<DWORD>(value->size());
            credential.CredentialBlob = reinterpret_cast<LPBYTE>(const_cast<char*>(value->data()));
            credential.Persist = CRED_PERSIST_LOCAL_MACHINE;
            credential.UserName = const_cast<LPWSTR>(L"studio");
            if (!CredWriteW(&credential, 0)) {
              result->Error("storage", "Unable to save service credential.");
              return;
            }
          }
          result->Success();
        } else {
          result->NotImplemented();
        }
      });
  SetChildContent(flutter_controller_->view()->GetNativeWindow());

  flutter_controller_->engine()->SetNextFrameCallback([&]() {
    this->Show();
  });

  // Flutter can complete the first frame before the "show window" callback is
  // registered. The following call ensures a frame is pending to ensure the
  // window is shown. It is a no-op if the first frame hasn't completed yet.
  flutter_controller_->ForceRedraw();

  return true;
}

void FlutterWindow::OnDestroy() {
  secure_channel_ = nullptr;
  if (flutter_controller_) {
    flutter_controller_ = nullptr;
  }

  Win32Window::OnDestroy();
}

LRESULT
FlutterWindow::MessageHandler(HWND hwnd, UINT const message,
                              WPARAM const wparam,
                              LPARAM const lparam) noexcept {
  // Give Flutter, including plugins, an opportunity to handle window messages.
  if (flutter_controller_) {
    std::optional<LRESULT> result =
        flutter_controller_->HandleTopLevelWindowProc(hwnd, message, wparam,
                                                      lparam);
    if (result) {
      return *result;
    }
  }

  switch (message) {
    case WM_FONTCHANGE:
      flutter_controller_->engine()->ReloadSystemFonts();
      break;
  }

  return Win32Window::MessageHandler(hwnd, message, wparam, lparam);
}
