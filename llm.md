# llm.md

Please provide your instructions under the "Prompt" section below.

## Prompt

Please review the cloudflare email worker in src. Ensure it follows our coding conventions and makes full use of any cloudflare worker functionality for logging, error capture etc.
We should ensure the script is as robust as possible - given it is not interactive with a user, and exposed to third parties via email. We need to ensure it can't become an attack vector.
Please keep the file as javascript.
## Assistant's Response

<<LLM_FILE_START: src/odoo-cloudflare-email-worker.js>>
'use strict';

/**
 * Email Processor Module
 *
 * Processes incoming email messages and sends them to Odoo CRM after filtering them for spam and other criteria.
 *
 * Author: Troy Kelly
 * Contact: troy@aperim.com
 *
 * Code History:
 * - Created on 2024-10-21 by Troy Kelly
 * - Updated SpamFilter to include sender name analysis for Gmail addresses.
 * - Modified on 2024-10-22 to fix response handling and add error capturing.
 * - Reviewed on 2024-10-22 to enhance robustness and compliance with coding standards.
 */

/**
 * Asynchronously converts a stream to a Uint8Array.
 * @param {ReadableStream} stream The stream to convert.
 * @param {number} streamSize The expected size of the stream.
 * @return {Promise<Uint8Array>} The resulting Uint8Array.
 */
async function streamToUint8Array(stream, streamSize) {
  const result = new Uint8Array(streamSize);
  let bytesRead = 0;
  const reader = stream.getReader();

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    result.set(value, bytesRead);
    bytesRead += value.length;
  }

  return result;
}

/**
 * Converts an ArrayBuffer to a base64 encoded string.
 * @param {ArrayBuffer} buffer The buffer to convert.
 * @return {string} The base64 encoded string.
 */
function arrayBufferToBase64(buffer) {
  let binary = '';
  const bytes = new Uint8Array(buffer);
  const len = bytes.byteLength;
  // Process in chunks to avoid stack overflow with large buffers
  for (let i = 0; i < len; i += 8192) {
    const chunk = bytes.subarray(i, i + 8192);
    binary += String.fromCharCode.apply(null, chunk);
  }
  return btoa(binary);
}

/**
 * Base class for email filters.
 */
class EmailFilter {
  /**
   * Creates an instance of EmailFilter.
   * @param {ForwardableEmailMessage} message The email message to check.
   */
  constructor(message) {
    /** @type {ForwardableEmailMessage} */
    this.message = message;
  }

  /**
   * Checks the message and returns an object indicating whether to ingest.
   * @return {{ingest: boolean, reason?: string}} Result of the check.
   */
  check() {
    // Default implementation allows all messages.
    return { ingest: true };
  }
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
   * @param {ForwardableEmailMessage} message The email message to check.
   */
  constructor(message) {
    super(message);
  }

  /**
   * Checks if the message is spam.
   * @return {{ingest: boolean, reason?: string}} Result of the check.
   */
  check() {
    const blocklist = ['spam@example.com', 'blocked@example.com'];
    const fromHeader = this.message.headers.get('from') || '';

    // Extract the sender's email from the 'From' header
    const emailMatch = fromHeader.match(/<([^>]+)>/);
    const senderEmail = emailMatch ? emailMatch[1] : fromHeader;
    const senderEmailLower = senderEmail.toLowerCase();

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
      const nameMatch = fromHeader.match(/^(.*)<[^>]+>/);
      const senderName = nameMatch ? nameMatch[1].trim() : '';

      // If sender name is empty, reject the message
      if (!senderName) {
        return {
          ingest: false,
          reason: 'Sender name is missing.',
        };
      }

      // Check if the sender name is a continuous string of letters and optionally numbers
      // e.g., matches /^[A-Za-z0-9]+$/
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
    const spamKeywords = ['viagra', 'prince', 'winner'];
    const subject = this.message.headers.get('subject') || '';
    const lowercaseSubject = subject.toLowerCase();
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
 * Sends the email content to Odoo CRM.
 * @param {string} base64Email The base64 encoded email content.
 * @param {object} options Configuration options for Odoo connection.
 * @return {Promise<{success: boolean, data?: string, error?: string}>} Result of the operation.
 */
async function sendToOdooCRM(base64Email, options) {
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
<value><base64>${base64Email}</base64></value>
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

  const fetchOptions = {
    method: 'POST',
    headers: headers,
    body: xml,
  };

  try {
    const response = await fetch(url, fetchOptions);
    const data = await response.text();

    if (!response.ok) {
      console.error(`HTTP Error: ${response.status} ${response.statusText}`);
      return {
        success: false,
        error: `Unable to deliver to CRM. ${response.status} ${response.statusText}`,
      };
    }

    // Adjusted regex to only match <int> within <params>
    const regexpSuccess = /<methodResponse>\s*<params>[\s\S]*?<int>(\d+)<\/int>[\s\S]*?<\/params>\s*<\/methodResponse>/im;
    const responseSuccess = regexpSuccess.exec(data);

    // Regex to detect faults
    const faultRegex = /<fault>[\s\S]*?<value>[\s\S]*?<struct>[\s\S]*?<member>[\s\S]*?<name>faultString<\/name>[\s\S]*?<value>[\s\S]*?<string>(.*?)<\/string>[\s\S]*?<\/value>[\s\S]*?<\/member>[\s\S]*?<\/struct>[\s\S]*?<\/value>[\s\S]*?<\/fault>/im;
    const faultMatch = faultRegex.exec(data);

    if (responseSuccess && responseSuccess.length === 2 && parseInt(responseSuccess[1], 10) > 0) {
      console.log(`Successfully processed. Record ${parseInt(responseSuccess[1], 10)}`);
      // Optionally, store or log the response data
      return { success: true, data };
    } else if (faultMatch && faultMatch.length === 2) {
      const faultString = faultMatch[1];
      console.error(`Fault response from API: ${faultString}`);
      return {
        success: false,
        error: `Unable to deliver to CRM: ${faultString}`,
      };
    } else {
      console.error(`Invalid response from API: ${data}`);
      return {
        success: false,
        error: 'Invalid recipient or unexpected CRM response.',
      };
    }
  } catch (error) {
    console.error('Error during CRM communication:', error);
    return {
      success: false,
      error: 'Unable to deliver to CRM due to a communication error.',
    };
  }
}

/**
 * Default export object containing the email processing function.
 */
export default {
  /**
   * Processes an incoming email message and sends it to Odoo CRM.
   * @param {ForwardableEmailMessage} message The email message to process.
   * @param {object} env The environment variables.
   * @param {ExecutionContext} ctx The execution context.
   * @return {Promise<void>}
   */
  async email(message, env, ctx) {
    try {
      // Define the array of email filters
      const emailFilters = [SpamFilter /* , AdditionalFilters */];

      // Apply email filters
      for (const FilterClass of emailFilters) {
        const filter = new FilterClass(message);
        const result = filter.check();

        if (!result.ingest) {
          console.warn(`Email rejected by ${FilterClass.name}: ${result.reason}`);
          message.setReject(result.reason || 'Message rejected by filter.');
          return;
        }
      }

      // Try to convert the email stream to a Uint8Array
      let rawEmail;
      try {
        rawEmail = await streamToUint8Array(message.raw, message.rawSize);
      } catch (error) {
        console.error('Error reading email stream:', error);
        message.setReject('Unable to process email data.');
        return;
      }

      const base64Email = arrayBufferToBase64(rawEmail);

      // Gather the necessary options from environment variables
      const options = {
        database: env.ODOO_DATABASE || 'company',
        userid: env.ODOO_USERID || '2',
        password: env.ODOO_PASSWORD || 'password',
        host: env.ODOO_HOST || 'crm.example.com',
        port: env.ODOO_PORT || '443',
        protocol: env.ODOO_PROTOCOL || 'https',
      };

      // Send to Odoo CRM
      const crmResult = await sendToOdooCRM(base64Email, options);

      if (!crmResult.success) {
        console.error('Failed to send email to CRM:', crmResult.error);
        message.setReject(crmResult.error || 'Unable to deliver to CRM.');
        return;
      }

      // Successfully processed
      console.log('Email successfully delivered to CRM.');

    } catch (error) {
      // Catch any unhandled errors
      console.error('Unexpected error during email processing:', error);
      message.setReject('Internal server error during email processing.');
    }
  },
};
<<LLM_FILE_END>>