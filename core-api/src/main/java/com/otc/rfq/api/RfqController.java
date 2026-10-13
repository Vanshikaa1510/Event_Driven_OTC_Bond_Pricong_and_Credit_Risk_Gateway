package com.otc.rfq.api;

import com.otc.rfq.service.RfqService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Size;
import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.UUID;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

@RestController
@Validated
@RequestMapping("/api/rfqs")
public class RfqController {
    private static final int MAX_EXTRACTED_TEXT_LENGTH = 20_000;
    private final RfqService rfqService;

    public RfqController(RfqService rfqService) {
        this.rfqService = rfqService;
    }

    @PostMapping
    public ResponseEntity<RfqResponse> submit(
            @Valid @RequestBody CreateRfqRequest request,
            @RequestHeader(value = "Idempotency-Key", required = false) @Size(max = 128) String idempotencyKey) {
        RfqResponse response = rfqService.submit(request, idempotencyKey);
        return ResponseEntity.created(URI.create("/api/rfqs/" + response.id())).body(response);
    }

    @PostMapping(value = "/documents", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<RfqResponse> submitDocument(
            @RequestPart("file") MultipartFile file,
            @RequestParam("clientId") String clientId,
            @RequestHeader(value = "Idempotency-Key", required = false) @Size(max = 128) String idempotencyKey) {
        String rawText = extractText(file);
        if (clientId.isBlank() || clientId.length() > 64
                || rawText.isBlank() || rawText.length() > MAX_EXTRACTED_TEXT_LENGTH) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Client ID and extracted RFQ text are invalid");
        }
        RfqResponse response = rfqService.submit(new CreateRfqRequest(rawText, clientId), idempotencyKey);
        return ResponseEntity.created(URI.create("/api/rfqs/" + response.id())).body(response);
    }

    @GetMapping("/{id}")
    public RfqResponse get(@PathVariable UUID id) {
        return rfqService.get(id);
    }

    @GetMapping("/{id}/history")
    public List<RfqAuditEventResponse> history(@PathVariable UUID id) {
        return rfqService.getAuditHistory(id);
    }

    @GetMapping
    public List<RfqResponse> list(@RequestParam(defaultValue = "50") int limit) {
        return rfqService.list(Math.clamp(limit, 1, 200));
    }

    private String extractText(MultipartFile file) {
        if (file.isEmpty() || file.getSize() > 10_000_000) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Upload must be non-empty and at most 10 MB");
        }
        String filename = file.getOriginalFilename() == null ? "" : file.getOriginalFilename().toLowerCase();
        try {
            if (filename.endsWith(".pdf")) {
                try (PDDocument document = Loader.loadPDF(file.getBytes())) {
                    return new PDFTextStripper().getText(document).strip();
                }
            }
            if (filename.endsWith(".txt") || filename.endsWith(".eml")) {
                return new String(file.getBytes(), StandardCharsets.UTF_8).strip();
            }
        } catch (IOException exception) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Could not extract text from the uploaded document", exception);
        }
        throw new ResponseStatusException(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "Supported uploads are PDF, TXT, and EML");
    }
}