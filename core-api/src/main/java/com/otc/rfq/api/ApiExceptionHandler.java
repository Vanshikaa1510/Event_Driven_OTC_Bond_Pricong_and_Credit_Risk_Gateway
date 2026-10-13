package com.otc.rfq.api;

import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class ApiExceptionHandler {
    @ExceptionHandler(RfqNotFoundException.class)
    @ResponseStatus(HttpStatus.NOT_FOUND)
    public Map<String, String> notFound(RfqNotFoundException exception) {
        return Map.of("error", exception.getMessage());
    }

    public static class RfqNotFoundException extends RuntimeException {
        public RfqNotFoundException(UUID id) {
            super("RFQ not found: " + id);
        }
    }
}