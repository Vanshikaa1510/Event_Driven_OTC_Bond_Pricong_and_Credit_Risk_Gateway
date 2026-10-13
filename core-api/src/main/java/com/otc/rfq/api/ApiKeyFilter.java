package com.otc.rfq.api;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class ApiKeyFilter extends OncePerRequestFilter {
    private static final String API_KEY_HEADER = "X-API-Key";
    private final byte[] configuredKey;

    public ApiKeyFilter(@Value("${rfq.api.key}") String apiKey) {
        if (apiKey == null || apiKey.length() < 32 || apiKey.toLowerCase().startsWith("replace-with-")) {
            throw new IllegalStateException("RFQ_API_KEY must be at least 32 characters and must not be a placeholder");
        }
        this.configuredKey = apiKey.getBytes(StandardCharsets.UTF_8);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String apiPath = request.getContextPath() + "/api";
        String requestPath = request.getRequestURI();
        return !requestPath.equals(apiPath) && !requestPath.startsWith(apiPath + "/");
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String presentedKey = request.getHeader(API_KEY_HEADER);
        byte[] candidate = presentedKey == null ? new byte[0] : presentedKey.getBytes(StandardCharsets.UTF_8);
        if (!MessageDigest.isEqual(configuredKey, candidate)) {
            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            response.setContentType(MediaType.APPLICATION_JSON_VALUE);
            response.setHeader("Cache-Control", "no-store");
            response.getWriter().write("{\"error\":\"Unauthorized\"}");
            return;
        }
        filterChain.doFilter(request, response);
    }
}
