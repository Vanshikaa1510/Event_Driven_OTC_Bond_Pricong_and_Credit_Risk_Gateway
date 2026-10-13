package com.otc.rfq.api;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record CreateRfqRequest(
        @NotBlank @Size(max = 20000) String rawText,
        @NotBlank @Size(max = 64) String clientId) {}