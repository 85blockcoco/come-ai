// Local macOS Vision OCR helper for Côme AI Career Agent.
//
// It is intentionally a very small Objective-C command-line program rather
// than a Python package dependency. Apple clang compiles it quickly on Intel
// Macs with Command Line Tools installed. It reads one local PDF, performs
// Vision text recognition on-device, and writes one JSON object to stdout.

#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#import <PDFKit/PDFKit.h>
#import <Vision/Vision.h>

static void write_error(NSString *message) {
    fprintf(stderr, "%s\n", message.UTF8String ?: "OCR local indisponible.");
}

static NSArray<NSString *> *recognise_image(CGImageRef image, NSError **error_out) {
    if (!image) {
        if (error_out) {
            *error_out = [NSError errorWithDomain:@"ComeAIOCR" code:1 userInfo:nil];
        }
        return nil;
    }

    __block NSMutableArray<NSString *> *lines = [NSMutableArray array];
    __block NSError *recognition_error = nil;
    VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc]
        initWithCompletionHandler:^(VNRequest *finished_request, NSError *request_error) {
            if (request_error) {
                recognition_error = request_error;
                return;
            }
            for (VNRecognizedTextObservation *observation in finished_request.results) {
                VNRecognizedText *candidate = [[observation topCandidates:1] firstObject];
                if (candidate.string.length > 0) {
                    [lines addObject:candidate.string];
                }
            }
        }];
    request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
    request.usesLanguageCorrection = YES;
    request.minimumTextHeight = 0.008;

    VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:image options:@{}];
    NSError *handler_error = nil;
    if (![handler performRequests:@[request] error:&handler_error] || recognition_error) {
        if (error_out) {
            *error_out = recognition_error ?: handler_error;
        }
        return nil;
    }
    return lines;
}

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        if (argc < 2) {
            write_error(@"Usage: vision_ocr INPUT [MAX_PAGES]");
            return 2;
        }
        NSString *input_path = [NSString stringWithUTF8String:argv[1]];
        NSInteger requested_pages = argc >= 3 ? MAX(1, atoi(argv[2])) : 8;
        NSInteger max_pages = MIN(requested_pages, 12);
        NSURL *input_url = [NSURL fileURLWithPath:input_path];
        PDFDocument *document = [[PDFDocument alloc] initWithURL:input_url];
        if (!document || document.pageCount < 1) {
            write_error(@"PDF non lisible par l’OCR local.");
            return 2;
        }

        NSInteger pages = MIN(document.pageCount, max_pages);
        BOOL truncated = document.pageCount > max_pages;
        NSMutableArray<NSString *> *warnings = [NSMutableArray array];
        if (truncated) {
            [warnings addObject:[NSString stringWithFormat:@"OCR limité aux %ld premières pages du PDF.", (long)max_pages]];
        }
        NSMutableArray<NSString *> *page_texts = [NSMutableArray array];
        for (NSInteger index = 0; index < pages; index++) {
            PDFPage *page = [document pageAtIndex:index];
            if (!page) {
                continue;
            }
            NSImage *image = [page thumbnailOfSize:NSMakeSize(2400, 3400) forBox:kPDFDisplayBoxMediaBox];
            NSRect rect = NSMakeRect(0, 0, image.size.width, image.size.height);
            CGImageRef rendered = [image CGImageForProposedRect:&rect context:nil hints:nil];
            NSError *error = nil;
            NSArray<NSString *> *lines = recognise_image(rendered, &error);
            if (!lines) {
                write_error(@"L’OCR macOS Vision n’a pas pu lire ce document.");
                return 2;
            }
            if (lines.count > 0) {
                [page_texts addObject:[lines componentsJoinedByString:@"\n"]];
            }
        }

        NSDictionary *payload = @{
            @"text": [page_texts componentsJoinedByString:@"\n\n"],
            @"pages": @(pages),
            @"truncated": @(truncated),
            @"warnings": warnings,
        };
        NSError *json_error = nil;
        NSData *json = [NSJSONSerialization dataWithJSONObject:payload options:0 error:&json_error];
        if (!json) {
            write_error(@"L’OCR local n’a pas pu préparer son résultat.");
            return 2;
        }
        fwrite(json.bytes, 1, json.length, stdout);
        fputc('\n', stdout);
        return 0;
    }
}
