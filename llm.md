# llm.md

Please provide your instructions under the "Prompt" section below.

## Prompt

Please review the cloudflare email worker in src. Ensure it follows our coding conventions and makes full use of any cloudflare worker functionality for logging, error capture etc.
We should ensure the script is as robust as possible - given it is not interactive with a user, and exposed to third parties via email. We need to ensure it can't become an attack vector.
## Assistant's Response

<<LLM_FILE_START: src/odoo-cloudflare-email-worker.ts>>
```typescript
/**
 * Email Processor Module
 *
 * Processes incoming email messages and sends them to Odoo CRM after filtering them for spam and other criteria.
 *
 * Author: Troy Kelly
 * Contact: troy@aperim.com
 *
 * Code History:
 * - Created on 21 October 2024 by Troy Kelly
 * - Updated SpamFilter to include sender name analysis for Gmail addresses.
 * - Modified on 22 October 2024 to fix response handling and add error capturing.
 */

/**
 * Represents the environment variables used by the worker.
 */
interface Env {
  ODOO_DATABASE?: string;
  ODOO_USERID?: string;
  ODOO_PASSWORD?: string;
  ODOO_HOST?: string;
  ODOO_PORT?: string;
  ODOO_PROTOCOL?: string;
}

/**
 * Represents the result of a filter check.
 */
interface FilterResult {
  ingest: boolean;
  reason?: string;
}

/**
 * Asynchronously converts a stream to a Uint8Array.
 * @param stream - The stream to convert.
 * @param streamSize - The expected size of the stream.
 * @returns The resulting Uint8Array.
 */
async function streamToArrayBuffer(
  stream: ReadableStream<Uint8Array>,
  streamSize: number
): Promise<Uint8Array> {
  const result = new Uint8Array(streamSize);
  let bytesRead = 0;
  const reader = stream.getReader();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) {
      result.set(value, bytesRead);
      bytesRead += value.length;
    }
  }

  return result;
}

/**
 * Converts an ArrayBuffer to a base64 encoded string.
 * @param arrayBuffer - The buffer to convert.
 * @returns The base64 encoded string.
 */
function base64ArrayBuffer(arrayBuffer: ArrayBuffer): string {
  let binary = '';
  const bytes = new Uint8Array(arrayBuffer);
  const len = bytes.byteLength;
  const chunkSize = 0x8000; // Arbitrary chunk size to prevent call stack overflow

  for (let i = 0; i < len; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode.apply(null, Array.from(chunk));
  }

  return btoa(binary);
}

/**
 * Base class for email filters.
 */
abstract class EmailFilter {
  protected message: ForwardableEmailMessage;

  /**
   * Creates an instance of EmailFilter.
   * @param message - The email message to check.
   */
  constructor(message: ForwardableEmailMessage) {
    this.message = message;
  }

  /**
   * Checks the message and returns an object indicating whether to ingest.
   * @returns Result of the check.
   */
  abstract check(): FilterResult;
}

/**
 * SpamFilter checks for common spam indicators and sender name patterns.
 *
 * This filter examines the sender's name for patterns commonly associated with spam,
 * especially for Gmail addresses. It checks if the sender's name is a continuous string
 * of letters and optionally numbers, with a relatively equal distribution of uppercase
 * and lowercase letters.
 */
class SpamFilter extends EmailFilter {
  /**
   * Creates an instance of SpamFilter.
   * @param message - The email message to check.
   */
  constructor(message: ForwardableEmailMessage) {
    super(message);
  }

  /**
   * Checks if the message is spam.
   * @returns Result of the check.
   */
  check(): FilterResult {
    const blocklist: string[] = ['spam@example.com', 'blocked@example.com'];
    const fromHeader: string = this.message.headers.get('from') || '';

    // Extract the sender's email from the 'From' header
    const emailMatch: RegExpMatchArray | null = fromHeader.match(/<([^>]+)>/);
    const senderEmail: string = emailMatch ? emailMatch[1] : fromHeader;
    const senderEmailLower: string = senderEmail.toLowerCase();

    // Check if sender is in blocklist
    if (blocklist.includes(senderEmailLower)) {
      return {
        ingest: false,
        reason: 'Sender is blocked.',
      };
    }

    // Logic for Gmail addresses
    if (senderEmailLower.endsWith('@gmail.com')) {
      // Extract the sender's name from the 'From' header
      const nameMatch: RegExpMatchArray | null = fromHeader.match(/^(.*)<[^>]+>/);
      const senderName: string = nameMatch ? nameMatch[1].trim() : '';

      // If sender name is empty, reject the message
      if (!senderName) {
        return {
          ingest: false,
          reason: 'Sender name is missing.',
        };
      }

      // Check if the sender name is a continuous string of letters and optionally numbers
      if (/^[A-Za-z0-9]+$/.test(senderName)) {
        const letters = senderName.replace(/[^A-Za-z]/g, '');
        const totalLetters = letters.length;

        if (totalLetters >= 8) {
          const uppercaseLetters = senderName.replace(/[^A-Z]/g, '');
          const lowercaseLetters = senderName.replace(/[^a-z]/g, '');

          const uppercaseCount = uppercaseLetters.length;
          const lowercaseCount = lowercaseLetters.length;

          const uppercasePercentage = (uppercaseCount / totalLetters) * 100;
          const lowercasePercentage = (lowercaseCount / totalLetters) * 100;

          // Check for relatively equal distribution (between 40% and 60%)
          if (
            uppercasePercentage >= 40 &&
            uppercasePercentage <= 60 &&
            lowercasePercentage >= 40 &&
            lowercasePercentage <= 60
          ) {
            return {
              ingest: false,
              reason: 'Sender name resembles spam pattern.',
            };
          }
        }
      }
    }

    // Check for spam keywords in the subject
    const spamKeywords: string[] = ['viagra', 'prince', 'winner'];
    const subject: string = this.message.headers.get('subject') || '';
    const lowercaseSubject: string = subject.toLowerCase();
    for (const keyword of spamKeywords) {
      if (lowercaseSubject.includes(keyword)) {
        return {
          ingest: false,
          reason: 'Message contains spam keywords.',
        };
      }
    }

    // If none of the checks failed, allow the message
    return { ingest: true };
  }
}

/**
 * Default export object containing the email processing function.
 */
export default {
  /**
   * Processes an incoming email message and sends it to Odoo CRM.
   * @param message - The email message to process.
   * @param env - The environment variables.
   * @param ctx - The execution context.
   * @returns Promise resolving when processing is complete.
   */
  async email(message: ForwardableEmailMessage, env: Env, ctx: ExecutionContext): Promise<void> {
    // Define the array of email filters
    const emailFilters: EmailFilter[] = [new SpamFilter(message) /*, AdditionalFilters*/];

    // Apply email filters
    for (const filter of emailFilters) {
      const result = filter.check();

      if (!result.ingest) {
        console.warn(`Email rejected by ${filter.constructor.name}: ${result.reason}`);
        message.setReject(result.reason || 'Message rejected by filter.');
        return;
      }
    }

    let rawEmail: Uint8Array;

    // Try to convert the email stream to a Uint8Array
    try {
      rawEmail = await streamToArrayBuffer(message.raw, message.rawSize);
    } catch (error) {
      console.warn('No valid raw email data.');
      console.error(error);
      message.setReject('Unable to process email data.');
      return;
    }

    // Gather the necessary options from environment variables
    const options = {
      database: env.ODOO_DATABASE || 'company',
      userid: env.ODOO_USERID || '2',
      password: env.ODOO_PASSWORD || 'password',
      host: env.ODOO_HOST || 'crm.example.com',
      port: env.ODOO_PORT || '443',
      protocol: env.ODOO_PROTOCOL || 'https',
    };

    const url = `${options.protocol}://${options.host}:${options.port}/xmlrpc/2/object`;

    // Construct the XML payload ensuring no leading whitespace
    const xml = `<?xml version="1.0"?>
<methodCall>
<methodName>execute_kw</methodName>
<params>
<param><value><string>${options.database}</string></value></param>
<param><value><int>${options.userid}</int></value></param>
<param><value><string>${options.password}</string></value></param>
<param><value><string>mail.thread</string></value></param>
<param><value><string>message_process</string></value></param>
<param>
<value>
<array>
<data>
<value><boolean>0</boolean></value>
<value><base64>${base64ArrayBuffer(rawEmail.buffer)}</base64></value>
</data>
</array>
</value>
</param>
<param><value><struct></struct></value></param>
</params>
</methodCall>`;

    const headers = {
      'Content-Type': 'application/xml',
    };

    const fetchOptions: RequestInit = {
      method: 'POST',
      headers: headers,
      body: xml,
    };

    // Make the request to the CRM
    try {
      const response = await fetch(url, fetchOptions);
      const data = await response.text();

      if (!response.ok) {
        console.error(`HTTP Error: ${response.status} ${response.statusText}`);
        message.setReject(`Unable to deliver to CRM. ${response.status} ${response.statusText}`);
        return;
      }

      // Adjusted regex to only match <int> within <params>
      const regexpSuccess = /<methodResponse>\s*<params>[\s\S]*?<int>(\d+)<\/int>[\s\S]*?<\/params>\s*<\/methodResponse>/im;
      const responseSuccess = regexpSuccess.exec(data);

      // New regex to detect faults
      const faultRegex = /<fault>[\s\S]*?<value>[\s\S]*?<struct>[\s\S]*?<member>[\s\S]*?<name>faultString<\/name>[\s\S]*?<value>[\s\S]*?<string>(.*?)<\/string>[\s\S]*?<\/value>[\s\S]*?<\/member>[\s\S]*?<\/struct>[\s\S]*?<\/value>[\s\S]*?<\/fault>/im;
      const faultMatch = faultRegex.exec(data);

      if (responseSuccess && responseSuccess.length === 2 && parseInt(responseSuccess[1], 10) > 0) {
        console.log(`Successfully processed. Record ${parseInt(responseSuccess[1], 10)}`);
        console.log(JSON.stringify({ url, xml, data }, null, 2));
      } else if (faultMatch && faultMatch.length === 2) {
        const faultString = faultMatch[1];
        console.error(`Fault response from API: ${faultString}`);
        message.setReject(`Unable to deliver to CRM: ${faultString}`);
        return;
      } else {
        console.error(`Invalid response from API: ${data}`);
        message.setReject('Invalid recipient or unexpected CRM response.');
        return;
      }
    } catch (error) {
      console.error('Error during CRM communication:', error);
      message.setReject('Unable to deliver to CRM due to a communication error.');
      return;
    }
  },
};
```
<<LLM_FILE_END>>